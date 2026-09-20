"""Durable media jobs, with per-step provider IDs and restart-safe polling.

One process, as configured by Dockerfile. A crash during submission is marked
needs_attention instead of risking a second paid submission. Existing provider
requests are polled again after a restart; completed files live on the volume.
"""
import asyncio
import json
import logging
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image
from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .fal_provider import FalProvider, ProviderError, IMAGE_MODEL, IMAGE_EDIT_MODEL, VIDEO_MODEL, VIDEO_IMAGE_MODEL, AUDIO_MODEL
from .integrations import provider_key
from .media_providers import (OpenAIProvider, HiggsfieldProvider, IMAGE_MODELS, UGC_MODEL, UGC_FORMATS,
                              public_https, public_session)
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
        choice = IMAGE_MODELS[inputs.get('image_model', 'nano_banana')]
        model = choice['model']
        if choice['provider'] == 'fal' and inputs.get('reference_asset_id'):
            model = IMAGE_EDIT_MODEL
        return [{'kind': 'image', 'provider': choice['provider'], 'model': model,
                 'prompt': inputs['prompt']}]
    if kind == 'audio':
        return [{'kind': 'audio', 'model': AUDIO_MODEL}]
    ugc = inputs.get('video_mode') == 'ugc'
    steps = [{'kind': 'video', 'provider': 'higgsfield' if ugc else 'fal',
              'model': UGC_MODEL if ugc else VIDEO_IMAGE_MODEL if inputs.get('reference_asset_id') else VIDEO_MODEL,
              'prompt': s['prompt'], 'spoken_text': s.get('spoken_text', ''),
              'duration': s['duration']} for s in inputs['scenes']]
    if inputs.get('voiceover') and not ugc:
        steps.append({'kind': 'audio', 'model': AUDIO_MODEL})
    if inputs.get('captions'):
        steps.append({'kind': 'captions', 'provider': 'openai', 'model': 'whisper-1'})
    return steps


def payload_for(step, inputs, reference=None, creator=None):
    if step['kind'] == 'audio':
        # Read only the operator-approved spoken text, never the entire script table.
        return {'text': inputs['voiceover'], 'voice': inputs['voice'],
                'language_code': inputs['language'], 'stability': 0.5}
    prompt = step['prompt']
    if step['kind'] == 'image':
        prompt += ('\nCreate a finished e-commerce advertising image with the supplied copy and brand identity.'
                   if inputs.get('image_purpose') == 'ad' else '\nCreate a professional e-commerce product image.')
        prompt += '\nUse only supplied product claims and exact requested text. For edits, change only what was requested.'
    if reference:
        prompt += '\nPreserve the exact product, packaging and identity in the reference image.'
    if inputs.get('brand_brief'):
        limit = 2500 if step['kind'] == 'video' else 10000
        prompt += ('\nBrand guidance: ' + inputs['brand_brief'])[:max(0, limit - len(prompt))]
    if step.get('provider') == 'higgsfield':
        prompt = (f"Creator-led UGC advertisement. {UGC_FORMATS[inputs['ugc_format']]}\n"
                  'Image 1 is the exact product. Image 2 is the presenter identity. '
                  'Preserve both across every shot. Natural handheld creator footage, realistic interaction. '
                  'No generated subtitles, music, extra speech or added logos. '
                  f"Speak in {'Egyptian Arabic' if inputs['language'] == 'ar' else 'English'}, "
                  f"with natural synchronized lip movement.\nScene: {prompt}\n"
                  f"Say exactly: {step['spoken_text']}")
        return {'prompt': prompt, 'duration': step['duration'], 'image_urls': [reference, creator],
                'aspect_ratio': inputs['aspect_ratio'], 'resolution': '720p',
                'output_format': 'mp4', 'generate_audio': True}
    if step['kind'] == 'image' and step.get('provider') == 'openai':
        return {'prompt': prompt, 'size': {'1:1': '1024x1024', '9:16': '864x1536',
                                         '16:9': '1536x864'}[inputs['aspect_ratio']],
                'quality': inputs.get('image_quality', 'high')}
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


async def download_higgsfield(url, destination):
    """Higgsfield uses signed CDN/storage hosts; validate DNS at connection time."""
    from urllib.parse import urljoin
    tmp = destination.with_suffix('.part')
    try:
        async with public_session() as session:
            for _ in range(5):
                async with session.get(public_https(url), allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers['Location'])
                        continue
                    if response.status != 200:
                        raise ProviderError('تعذّر تنزيل فيديو Higgsfield؛ الطلب محفوظ لدى المزود.')
                    size = 0
                    with tmp.open('wb') as f:
                        async for chunk in response.content.iter_chunked(65536):
                            size += len(chunk)
                            if size > settings.max_upload_mb * 1024 * 1024:
                                raise ValueError('الفيديو أكبر من حد التخزين.')
                            f.write(chunk)
                    tmp.replace(destination)
                    return
            raise ValueError('عدد تحويلات رابط الفيديو غير صالح.')
    finally:
        tmp.unlink(missing_ok=True)


def reference_png(asset):
    with Image.open(safe_asset_path(asset)) as image:
        image = image.convert('RGB')
        image.thumbnail((2048, 2048))
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return buffer.getvalue()


async def command(*args, cwd=None):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, cwd=cwd)
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
    native_audio = job.inputs.get('video_mode') == 'ugc'
    for i, clip in enumerate(clips):
        dest = folder / f'clip_{i}.mp4'
        audio_args = ('-map', '0:v:0', '-map', '0:a:0', '-c:a', 'aac', '-ar', '48000', '-ac', '2') if native_audio else ('-an',)
        await command('ffmpeg', '-y', '-i', clip, *audio_args, '-vf',
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


def captions_ass(words, width, height):
    """Short word-timed lines; libass handles Arabic shaping and bidirectional text."""
    import math
    def timestamp(value):
        cs = round(value * 100)
        return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'
    def clean(text):
        # Strip ASS overrides/control characters, including injected \N sequences.
        return ''.join(c for c in str(text) if c.isprintable() and c not in '{}\\').strip()
    lines, group = [], []
    previous_end = 0.0
    for word in words:
        start, end = float(word['start']), float(word['end'])
        text = clean(word['word'])
        if not text or not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start or end > 185:
            continue
        start = max(start, previous_end)
        if end <= start:
            continue
        if group and (len(group) >= 6 or start - group[-1][1] > 0.6 or len(' '.join(w[2] for w in group)) + len(text) > 42):
            lines.append(group); group = []
        group.append((start, end, text)); previous_end = end
    if group:
        lines.append(group)
    if not lines:
        raise ValueError('لم نستخرج كلامًا مؤقتًا صالحًا للكابشن. راجع الصوت الناتج.')
    font = 42 if width <= 720 else 48
    header = (f'[Script Info]\nScriptType: v4.00+\nPlayResX: {width}\nPlayResY: {height}\nWrapStyle: 0\n'
              '[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
              'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
              f'Style: Default,Noto Sans Arabic,{font},&H00FFFFFF,&H00FFFFFF,&H00151515,&H80000000,0,0,0,0,100,100,0,0,1,3,1,2,45,45,{int(height * .12)},1\n'
              '[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n')
    return header + ''.join(f"Dialogue: 0,{timestamp(g[0][0])},{timestamp(g[-1][1])},Default,,0,0,0,,{' '.join(w[2] for w in g)}\n" for g in lines)


async def finish_video(job):
    source = await assemble(job)
    captions = next((s for s in job.steps if s['kind'] == 'captions'), None)
    if not captions:
        return source
    transcript = json.loads(Path(captions['local_path']).read_text(encoding='utf-8'))
    width, height = {'9:16': (720, 1280), '16:9': (1280, 720), '1:1': (720, 720)}[job.inputs['aspect_ratio']]
    subtitle = source.parent / 'captions.ass'
    subtitle.write_text(captions_ass(transcript.get('words', []), width, height), encoding='utf-8-sig')
    target = source.parent / 'captioned.mp4'
    # Only a generated constant enters the filter; no paths or user text in filter syntax.
    await command('ffmpeg', '-y', '-i', str(source), '-vf', 'ass=captions.ass',
                  '-c:v', 'libx264', '-preset', 'fast', '-c:a', 'copy', '-movflags', '+faststart',
                  str(target), cwd=str(source.parent))
    return target


async def tick(job_id):
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, job_id)
        if not job or job.status not in ACTIVE:
            return
        steps = [dict(s) for s in job.steps]
        step_index = next((i for i, s in enumerate(steps) if s.get('state') != 'done'), None)
        step = steps[step_index] if step_index is not None else None
        provider_name = step.get('provider', 'fal') if step else None
        if job.cancel_requested:
            if step and step.get('request_id') and provider_name != 'openai':
                try:
                    key = await provider_key(db, provider_name)
                    if key:
                        provider = (HiggsfieldProvider if provider_name == 'higgsfield' else FalProvider)(key)
                        await provider.cancel(step)
                except ProviderError:
                    pass  # Already completed requests cannot always be stopped.
            job.status = 'cancelled'
            job.error = 'تم وقف المراحل التالية وإرسال طلب إلغاء. قد يحاسب المزود على المرحلة التي بدأت بالفعل.'
            await db.commit()
            return
        if step_index is None:
            path = await finish_video(job) if job.kind == 'video' else Path(steps[0]['local_path'])
            mime = {'image': 'image/png', 'video': 'video/mp4', 'audio': 'audio/mpeg'}[job.kind]
            asset = Asset(brand_id=job.brand_id, kind=job.kind, path=str(path),
                          filename=f'{job.kind}-{job.id}{path.suffix}', media_type=mime,
                          size_bytes=path.stat().st_size, meta={'production_job_id': job.id})
            db.add(asset)
            await db.flush()
            job.asset_id, job.status = asset.id, 'done'
            await db.commit()
            return
        if step.get('state') == 'submitting' and not step.get('request_id'):
            job.status = 'needs_attention'
            job.error = f'انقطع الاتصال أثناء إرسال الطلب. راجع سجل {provider_name} قبل إنشاء طلب جديد لتجنب دفع التكلفة مرتين.'
            await db.commit()
            return
        key = await provider_key(db, provider_name)
        if not key:
            raise ValueError(f'أضف مفتاح {provider_name} من إعدادات الإنتاج.')
        provider = {'fal': FalProvider, 'openai': OpenAIProvider, 'higgsfield': HiggsfieldProvider}[provider_name](key)
        if not step.get('request_id'):
            reference, creator, references = None, None, []
            for field in ('reference_asset_id', 'creator_asset_id'):
                if not job.inputs.get(field) or step['kind'] not in ('image', 'video'):
                    continue
                asset = await db.get(Asset, job.inputs[field])
                if not asset or asset.brand_id != job.brand_id:
                    raise ValueError('الصورة المرجعية لم تعد متاحة.')
                if provider_name == 'fal':
                    prepared = await asyncio.to_thread(prepare_image, safe_asset_path(asset))
                    reference = f'data:{prepared.media_type};base64,{prepared.data}'
                else:
                    raw = await asyncio.to_thread(reference_png, asset)
                    references.append(raw)
                    if provider_name == 'higgsfield':
                        # Upload is not a generation and may safely be retried before submission.
                        url = await provider.upload(raw)
                        if field == 'reference_asset_id':
                            reference = url
                        else:
                            creator = url
                    else:
                        reference = True
            audio_path = None
            if step['kind'] == 'captions':
                source = await assemble(job)
                audio_path = source.parent / 'caption-audio.mp3'
                await command('ffmpeg', '-y', '-i', str(source), '-vn', '-ac', '1', '-ar', '16000',
                              '-b:a', '64k', str(audio_path))
                payload = None
            else:
                payload = payload_for(step, job.inputs, reference, creator)
            # Commit before the non-idempotent provider call; never auto-resubmit on timeout.
            step['state'] = 'submitting'
            steps[step_index] = step
            job.steps, job.status = steps, 'submitting'
            await db.commit()
            if provider_name == 'openai':
                if step['kind'] == 'image':
                    raw, request_id = await provider.image(step['model'], payload, references)
                    if len(raw) > settings.max_upload_mb * 1024 * 1024:
                        raise ValueError('الصورة الناتجة أكبر من حد التخزين.')
                    # Validate the actual image, not just the provider's claimed format.
                    with Image.open(BytesIO(raw)) as image:
                        image.verify()
                    path = storage_path(job.brand_id, job.id, f'step_{step_index}.png')
                    path.write_bytes(raw)
                else:
                    transcript, request_id = await provider.transcribe(audio_path, job.inputs['language'])
                    path = storage_path(job.brand_id, job.id, f'step_{step_index}.json')
                    path.write_text(json.dumps(transcript, ensure_ascii=False), encoding='utf-8')
                result = {'request_id': request_id or f'{job.id}-{step_index}', 'local_path': str(path)}
            else:
                result = await provider.submit(step['model'], payload)
            # The committed JSON is the ORM's baseline; never mutate it in place.
            steps = [dict(s) for s in job.steps]
            step = steps[step_index]
            step.update(result, state='done' if provider_name == 'openai' else 'running')
            # Fresh list forces SQLAlchemy JSON dirty tracking.
            job.steps, job.status = [dict(s) for s in steps], 'running'
            brand = await db.get(Brand, job.brand_id)
            db.add(UsageEvent(brand_id=job.brand_id, client_id=brand.client_id, user_id=job.user_id,
                              operation='production', reference_id=result['request_id'][:100], provider=provider_name,
                              model=step['model'], cost_usd=None))
            await db.commit()
            return
        state = await provider.status(step)
        if state.get('status') in ('FAILED', 'ERROR', 'CANCELLED'):
            raise ProviderError('المزود أنهى الطلب بدون ملف. راجع سجل حساب المزود.')
        if state.get('status') != 'COMPLETED':
            return
        result = state if provider_name == 'higgsfield' else await provider.result(step)
        output = result.get('images', [None])[0] if step['kind'] == 'image' else result.get(step['kind'])
        if not output or not output.get('url'):
            raise ValueError('المزود لم يرجع ملفًا صالحًا.')
        suffix = {'image': '.png', 'video': '.mp4', 'audio': '.mp3'}[step['kind']]
        path = storage_path(job.brand_id, job.id, f'step_{step_index}{suffix}')
        if provider_name == 'higgsfield':
            await download_higgsfield(output['url'], path)
        else:
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
