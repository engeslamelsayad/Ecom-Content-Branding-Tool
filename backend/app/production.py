"""Durable media jobs, with per-step provider IDs and restart-safe polling.

One process, as configured by Dockerfile. A crash during submission is marked
needs_attention instead of risking a second paid submission. Existing provider
requests are polled again after a restart; completed files live on the volume.
"""
import asyncio
import logging
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .fal_provider import FalProvider, ProviderError, IMAGE_MODEL, IMAGE_EDIT_MODEL, VIDEO_MODEL, VIDEO_IMAGE_MODEL, AUDIO_MODEL
from .integrations import fal_key
from .media import prepare_image, storage_path
from .models import Asset, Brand, ProductionJob, UsageEvent

log = logging.getLogger(__name__)
ACTIVE = ('queued', 'running', 'submitting', 'cancel_requested')


def safe_asset_path(asset) -> Path:
    path = Path(asset.path).resolve()
    if not path.is_relative_to(settings.storage_dir.resolve()) or not path.is_file():
        raise ValueError('الملف غير متاح في مساحة التخزين.')
    return path


def make_steps(kind, inputs):
    if kind == 'image':
        return [{'kind': 'image', 'model': IMAGE_EDIT_MODEL if inputs.get('reference_asset_id') else IMAGE_MODEL,
                 'prompt': inputs['prompt']}]
    if kind == 'audio':
        return [{'kind': 'audio', 'model': AUDIO_MODEL}]
    steps = [{'kind': 'video', 'model': VIDEO_IMAGE_MODEL if inputs.get('reference_asset_id') else VIDEO_MODEL,
              'prompt': s['prompt'], 'duration': s['duration']} for s in inputs['scenes']]
    if inputs.get('voiceover'):
        steps.append({'kind': 'audio', 'model': AUDIO_MODEL})
    return steps


def payload_for(step, inputs, reference=None):
    if step['kind'] == 'audio':
        # Read only the operator-approved spoken text, never the entire script table.
        return {'text': inputs['voiceover'], 'voice': inputs['voice'],
                'language_code': inputs['language'], 'stability': 0.5}
    prompt = step['prompt']
    if reference:
        prompt += '\nPreserve the exact product, packaging and identity in the reference image.'
    if inputs.get('brand_brief'):
        limit = 2500 if step['kind'] == 'video' else 10000
        prompt += ('\nBrand guidance: ' + inputs['brand_brief'])[:max(0, limit - len(prompt))]
    if step['kind'] == 'image':
        payload = {'prompt': prompt, 'aspect_ratio': inputs['aspect_ratio'],
                   'num_images': 1, 'output_format': 'png', 'resolution': '1K'}
        if reference:
            payload['image_urls'] = [reference]
        return payload
    payload = {'prompt': prompt, 'duration': str(step['duration']), 'generate_audio': False}
    if reference:
        payload['image_url'] = reference
    else:
        payload['aspect_ratio'] = inputs['aspect_ratio']
    return payload


def media_url(url):
    p = urlparse(url)
    allowed = p.hostname == 'fal.media' or (p.hostname or '').endswith('.fal.media') or p.hostname == 'storage.googleapis.com'
    if p.scheme != 'https' or not allowed or p.username or p.password or p.port not in (None, 443):
        raise ValueError('Unexpected provider media host')
    return url


async def download(url, destination):
    # Never send the API key to a media/CDN URL; check every redirect, bound bytes.
    tmp = destination.with_suffix(destination.suffix + '.part')
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
            for _ in range(5):
                async with client.stream('GET', media_url(url)) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers['location'])
                        continue
                    response.raise_for_status()
                    size = 0
                    with tmp.open('wb') as f:
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > settings.max_upload_mb * 1024 * 1024:
                                raise ValueError('الملف الناتج أكبر من حد التخزين.')
                            f.write(chunk)
                    tmp.replace(destination)
                    return
            raise ValueError('Too many media redirects')
    finally:
        tmp.unlink(missing_ok=True)


async def command(*args):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=180)
    except BaseException:
        proc.kill()
        await proc.communicate()
        raise
    if proc.returncode:
        raise ValueError('تعذّر تجميع الفيديو. الملفات الأصلية محفوظة؛ راجع تثبيت ffmpeg.')
    return out


async def assemble(job):
    folder = storage_path(job.brand_id, job.id, 'final.mp4').parent
    clips = [s['local_path'] for s in job.steps if s['kind'] == 'video']
    width, height = {'9:16': (720, 1280), '16:9': (1280, 720), '1:1': (720, 720)}[job.inputs['aspect_ratio']]
    normalized = []
    for i, clip in enumerate(clips):
        dest = folder / f'clip_{i}.mp4'
        await command('ffmpeg', '-y', '-i', clip, '-an', '-vf',
                      f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=25',
                      '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p', str(dest))
        normalized.append(dest)
    # Generated filenames only; user text never enters a concat file or shell.
    manifest = folder / 'clips.txt'
    manifest.write_text(''.join(f"file 'clip_{i}.mp4'\n" for i in range(len(normalized))), encoding='utf-8')
    silent = folder / 'silent.mp4'
    await command('ffmpeg', '-y', '-f', 'concat', '-safe', '1', '-i', str(manifest),
                  '-c', 'copy', '-movflags', '+faststart', str(silent))
    audio = next((s['local_path'] for s in job.steps if s['kind'] == 'audio'), None)
    if not audio:
        return silent
    # Never cut the narration: hold the final frame if speech is longer.
    duration = float((await command('ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                   '-of', 'default=noprint_wrappers=1:nokey=1', audio)).decode().strip())
    if not 0 < duration <= 180:
        raise ValueError('التعليق الصوتي أطول من 3 دقائق؛ اختصر النص وأعد الإنتاج.')
    final = folder / 'final.mp4'
    await command('ffmpeg', '-y', '-i', str(silent), '-i', audio,
                  '-vf', 'tpad=stop_mode=clone:stop_duration=180', '-map', '0:v:0', '-map', '1:a:0',
                  '-t', str(max(duration, sum(s['duration'] for s in job.steps if s['kind'] == 'video'))),
                  '-c:v', 'libx264', '-preset', 'fast', '-c:a', 'aac', '-movflags', '+faststart', str(final))
    return final


async def tick(job_id):
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, job_id)
        if not job or job.status not in ACTIVE:
            return
        key = await fal_key(db)
        if not key:
            raise ValueError('أضف مفتاح fal من إعدادات الإنتاج.')
        provider = FalProvider(key)
        steps = [dict(s) for s in job.steps]
        step_index = next((i for i, s in enumerate(steps) if s.get('state') != 'done'), None)
        if job.cancel_requested:
            if step_index is not None and steps[step_index].get('request_id'):
                try:
                    await provider.cancel(steps[step_index])
                except ProviderError:
                    pass  # Already completed requests cannot always be stopped.
            job.status = 'cancelled'
            job.error = 'تم وقف المراحل التالية وإرسال طلب إلغاء. قد يحاسب المزود على المرحلة التي بدأت بالفعل.'
            await db.commit()
            return
        if step_index is None:
            path = await assemble(job) if job.kind == 'video' else Path(steps[0]['local_path'])
            mime = {'image': 'image/png', 'video': 'video/mp4', 'audio': 'audio/mpeg'}[job.kind]
            asset = Asset(brand_id=job.brand_id, kind=job.kind, path=str(path),
                          filename=f'{job.kind}-{job.id}{path.suffix}', media_type=mime,
                          size_bytes=path.stat().st_size, meta={'production_job_id': job.id})
            db.add(asset)
            await db.flush()
            job.asset_id, job.status = asset.id, 'done'
            await db.commit()
            return
        step = steps[step_index]
        if step.get('state') == 'submitting' and not step.get('request_id'):
            job.status = 'needs_attention'
            job.error = 'انقطع الاتصال أثناء إرسال الطلب. راجع سجل fal قبل إنشاء طلب جديد لتجنب دفع التكلفة مرتين.'
            await db.commit()
            return
        if not step.get('request_id'):
            reference = None
            if job.inputs.get('reference_asset_id') and step['kind'] != 'audio':
                asset = await db.get(Asset, job.inputs['reference_asset_id'])
                if not asset or asset.brand_id != job.brand_id:
                    raise ValueError('الصورة المرجعية لم تعد متاحة.')
                prepared = await asyncio.to_thread(prepare_image, safe_asset_path(asset))
                reference = f'data:{prepared.media_type};base64,{prepared.data}'
            payload = payload_for(step, job.inputs, reference)
            # Commit before the non-idempotent provider call; never auto-resubmit on timeout.
            step['state'] = 'submitting'
            steps[step_index] = step
            job.steps, job.status = steps, 'submitting'
            await db.commit()
            result = await provider.submit(step['model'], payload)
            # The committed JSON is the ORM's baseline; never mutate it in place.
            steps = [dict(s) for s in job.steps]
            step = steps[step_index]
            step.update(result, state='running')
            # Fresh list forces SQLAlchemy JSON dirty tracking.
            job.steps, job.status = [dict(s) for s in steps], 'running'
            brand = await db.get(Brand, job.brand_id)
            db.add(UsageEvent(brand_id=job.brand_id, client_id=brand.client_id, user_id=job.user_id,
                              operation='production', reference_id=result['request_id'], provider='fal',
                              model=step['model'], cost_usd=None))
            await db.commit()
            return
        state = await provider.status(step)
        if state.get('status') != 'COMPLETED':
            return
        result = await provider.result(step)
        output = result.get('images', [None])[0] if step['kind'] == 'image' else result.get(step['kind'])
        if not output or not output.get('url'):
            raise ValueError('المزود لم يرجع ملفًا صالحًا.')
        suffix = {'image': '.png', 'video': '.mp4', 'audio': '.mp3'}[step['kind']]
        path = storage_path(job.brand_id, job.id, f'step_{step_index}{suffix}')
        await download(output['url'], path)
        step.update(state='done', local_path=str(path))
        job.steps, job.status = [dict(s) for s in steps], 'running'
        await db.commit()


async def worker():
    while True:
        try:
            async with SessionLocal() as db:
                ids = list(await db.scalars(select(ProductionJob.id).where(ProductionJob.status.in_(ACTIVE))))
        except Exception:
            log.warning('media queue database temporarily unavailable')
            await asyncio.sleep(settings.production_poll_seconds)
            continue
        for job_id in ids:
            try:
                await tick(job_id)
            except asyncio.CancelledError:
                raise
            except (httpx.TimeoutException, httpx.NetworkError):
                # Polling/downloads may be retried. A submitting step is recovered as uncertain.
                log.warning('media job %s temporarily unreachable', job_id)
            except Exception as exc:
                log.warning('media job %s failed: %s', job_id, type(exc).__name__)
                try:
                    async with SessionLocal() as db:
                        job = await db.get(ProductionJob, job_id)
                        if job:
                            job.status = 'error'
                            job.error = str(exc) if isinstance(exc, (ValueError, ProviderError)) else 'تعذّر الإنتاج. الملفات المكتملة محفوظة.'
                            await db.commit()
                except Exception:
                    log.warning('could not persist media job error; retrying next cycle')
        await asyncio.sleep(settings.production_poll_seconds)
