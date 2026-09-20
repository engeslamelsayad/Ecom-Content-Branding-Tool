import base64
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app import production, llm
from app.config import settings
from app.db import SessionLocal
from app.integrations import provider_key
from app.media_providers import HiggsfieldProvider, OpenAIProvider, ProviderError, UGC_MODEL, public_https
from app.models import Integration, ProductionJob, UsageEvent


def png():
    b = BytesIO(); Image.new('RGB', (20, 20), 'red').save(b, format='PNG'); return b.getvalue()


async def image_asset(env, brand=None):
    r = await env['api'].post(f"/api/brands/{brand or env['brand']}/assets",
        files={'file': ('photo.png', png(), 'image/png')}, data={'kind': 'image'})
    assert r.status_code == 201
    return r.json()['id']


def body(env, **kw):
    return dict(brand_id=env['brand'], idempotency_key='new-media-test-key', kind='image',
                prompt='Product in a studio', confirmed=True, **kw)


async def connect(env, name):
    key = 'local-test-key:secret-part' if name == 'higgsfield' else 'local-test-key-12345'
    r = await env['api'].put(f'/api/integrations/{name}', json={'key': key})
    assert r.status_code == 200
    return key


async def test_keys_defaults_permissions_and_missing_provider(env):
    api = env['api']
    for provider in ('openai', 'higgsfield'):
        key = await connect(env, provider)
        async with SessionLocal() as db:
            assert key not in (await db.get(Integration, provider)).encrypted_key
            assert await provider_key(db, provider) == key
        assert key not in (await api.get('/api/production/settings')).text
        env['as_user']('editor')
        assert (await api.put(f'/api/integrations/{provider}', json={'key': key})).status_code == 403
        assert (await api.post(f'/api/integrations/{provider}/check')).status_code == 403
        assert (await api.put('/api/production/settings', json={'image_model': 'flare'})).status_code == 403
        env['as_user']('owner')
    assert (await api.put('/api/production/settings', json={'image_model': 'flare'})).status_code == 200
    job = (await api.post('/api/production', json=body(env))).json()
    async with SessionLocal() as db:
        step = (await db.get(ProductionJob, job['id'])).steps[0]
        assert step['model'] == 'gpt-image-2.5-flare' and step['provider'] == 'openai'
    assert (await api.put('/api/integrations/higgsfield', json={'key': 'missing-delimiter'})).status_code == 422
    assert (await api.put('/api/integrations/unknown', json={'key': 'bad-value-12345'})).status_code == 422


async def test_unconfigured_openai_rejects_without_fal_fallback(env, monkeypatch):
    monkeypatch.setattr(settings, 'openai_api_key', '')
    r = await env['api'].post('/api/production', json=body(env, image_model='sunburst'))
    assert r.status_code == 409 and 'openai' in r.text


@pytest.mark.parametrize('model', ['sunburst', 'flare'])
async def test_openai_image_generation_edit_and_recovery(env, monkeypatch, model):
    await connect(env, 'openai')
    reference = await image_asset(env)
    provider = SimpleNamespace(image=AsyncMock(return_value=(png(), 'image-request-123')))
    monkeypatch.setattr(production, 'OpenAIProvider', lambda key: provider)
    request = body(env, image_model=model, reference_asset_id=reference, aspect_ratio='1:1')
    r = await env['api'].post('/api/production', json=request)
    jid = r.json()['id']
    assert (await env['api'].post('/api/production', json=request)).json()['id'] == jid
    await production.tick(jid)
    await production.tick(jid)
    await production.tick(jid)
    provider.image.assert_awaited_once()
    args = provider.image.call_args.args
    assert args[0] == f'gpt-image-2.5-{model}' and args[1]['size'] == '1024x1024'
    assert args[2][0].startswith(b'\x89PNG')
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, jid)
        assert job.status == 'done'
        event = await db.scalar(select(UsageEvent))
        assert event.provider == 'openai'


async def test_openai_uncertain_request_never_repeats(env, monkeypatch):
    await connect(env, 'openai')
    provider = SimpleNamespace(image=AsyncMock(side_effect=httpx.ReadTimeout('timeout')))
    monkeypatch.setattr(production, 'OpenAIProvider', lambda key: provider)
    jid = (await env['api'].post('/api/production', json=body(env, image_model='flare'))).json()['id']
    with pytest.raises(httpx.ReadTimeout):
        await production.tick(jid)
    await production.tick(jid)
    async with SessionLocal() as db:
        assert (await db.get(ProductionJob, jid)).status == 'needs_attention'
    provider.image.assert_awaited_once()


async def test_openai_http_images_edits_transcription_and_secret_safe_errors(monkeypatch, tmp_path):
    real = httpx.AsyncClient
    requests = []
    def handler(req):
        requests.append(req)
        assert req.headers['authorization'] == 'Bearer secret-never-in-errors'
        if req.url.path.endswith('generations'):
            data = json.loads(req.content)
            assert data['model'] == 'gpt-image-2.5-sunburst' and data['n'] == 1
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]}, headers={'x-request-id': 'request123'})
        if req.url.path.endswith('edits'):
            assert b'name="image[]"' in req.content and b'gpt-image-2.5-flare' in req.content
            return httpx.Response(200, json={'data': [{'b64_json': base64.b64encode(png()).decode()}]})
        if req.url.path.endswith('transcriptions'):
            assert b'timestamp_granularities[]' in req.content and b'whisper-1' in req.content
            return httpx.Response(200, json={'words': [{'start': 0, 'end': 1, 'word': 'مرحبا'}]})
        return httpx.Response(403, text='secret-never-in-errors')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = OpenAIProvider('secret-never-in-errors')
    payload = {'prompt': 'Product', 'size': '1024x1024', 'quality': 'high'}
    raw, rid = await p.image('gpt-image-2.5-sunburst', payload, [])
    assert raw == png() and rid == 'request123'
    await p.image('gpt-image-2.5-flare', payload, [png()])
    audio = tmp_path / 'a.mp3'; audio.write_bytes(b'fake audio')
    transcript, _ = await p.transcribe(audio, 'ar')
    assert transcript['words'][0]['word'] == 'مرحبا'
    with pytest.raises(ProviderError) as e:
        await p.check()
    assert 'secret-never-in-errors' not in str(e.value)


async def ugc_body(env):
    ref, creator = await image_asset(env), await image_asset(env)
    return {'brand_id': env['brand'], 'idempotency_key': 'ugc-unique-key', 'kind': 'video',
            'confirmed': True, 'video_mode': 'ugc', 'reference_asset_id': ref, 'creator_asset_id': creator,
            'scenes': [{'prompt': 'Show the product to camera', 'duration': 10, 'spoken_text': 'ده شكل المنتج وتفاصيله'}]}


async def test_ugc_validation_references_and_provider_dependencies(env):
    api = env['api']; await connect(env, 'higgsfield')
    b = await ugc_body(env)
    assert (await api.post('/api/production', json=dict(b, creator_asset_id=None))).status_code == 422
    foreign = await image_asset(env, env['other_brand'])
    assert (await api.post('/api/production', json=dict(b, creator_asset_id=foreign))).status_code == 404
    assert (await api.post('/api/production', json=dict(b, captions=True))).status_code == 409
    assert (await api.post('/api/production', json=dict(b, voiceover='separate voice'))).status_code == 422
    too_long = dict(b, scenes=[dict(b['scenes'][0], spoken_text='كلمة ' * 31)])
    assert (await api.post('/api/production', json=too_long)).status_code == 422
    env['as_user']('viewer')
    assert (await api.post('/api/production', json=b)).status_code == 403
    env['as_user']('owner')
    result = await api.post('/api/production', json=b)
    assert result.status_code == 201
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, result.json()['id'])
        assert len(job.steps) == 1 and job.steps[0]['provider'] == 'higgsfield'


async def test_higgsfield_durable_polling_native_speech_and_caption_step(env, monkeypatch, tmp_path):
    await connect(env, 'higgsfield'); await connect(env, 'openai')
    hf = SimpleNamespace(upload=AsyncMock(side_effect=['https://cdn.example/product.png', 'https://cdn.example/creator.png']),
        submit=AsyncMock(return_value={'request_id': '6e9e0825-45e1-4f6e-863e-cfd12a331234'}),
        status=AsyncMock(return_value={'status': 'COMPLETED', 'video': {'url': 'https://cdn.example/video.mp4'}}))
    oa = SimpleNamespace(transcribe=AsyncMock(return_value=({'words': [{'word': 'المنتج', 'start': 0, 'end': 1}]}, 'caption123')))
    monkeypatch.setattr(production, 'HiggsfieldProvider', lambda key: hf)
    monkeypatch.setattr(production, 'OpenAIProvider', lambda key: oa)
    async def download(url, path): path.write_bytes(b'fake-video')
    monkeypatch.setattr(production, 'download_higgsfield', download)
    source = tmp_path / 'combined.mp4'; source.write_bytes(b'combined')
    monkeypatch.setattr(production, 'assemble', AsyncMock(return_value=source))
    monkeypatch.setattr(production, 'command', AsyncMock(return_value=b''))
    monkeypatch.setattr(production, 'finish_video', AsyncMock(return_value=source))
    b = dict(await ugc_body(env), captions=True)
    jid = (await env['api'].post('/api/production', json=b)).json()['id']
    for _ in range(5): await production.tick(jid)
    hf.submit.assert_awaited_once(); oa.transcribe.assert_awaited_once()
    model, payload = hf.submit.call_args.args
    assert model == UGC_MODEL and payload['generate_audio'] is True
    assert payload['image_urls'] == ['https://cdn.example/product.png', 'https://cdn.example/creator.png']
    assert b['scenes'][0]['spoken_text'] in payload['prompt'] and 'Egyptian Arabic' in payload['prompt']
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, jid)
        assert job.status == 'done'
        assert [e.provider for e in await db.scalars(select(UsageEvent))] == ['higgsfield', 'openai']


async def test_higgsfield_protocol_status_cancel_and_failed_states(monkeypatch):
    real = httpx.AsyncClient; rid = '6e9e0825-45e1-4f6e-863e-cfd12a331234'
    def handler(req):
        assert req.url.host == 'api.higgsfield.ai'
        assert req.headers['authorization'] == 'Key test:secret'
        if req.url.path.endswith('/cancel'):
            assert req.method == 'POST'; return httpx.Response(204)
        if req.method == 'POST':
            return httpx.Response(200, json={'request_id': rid, 'status_url': 'https://evil.example/steal-key'})
        return httpx.Response(200, json={'status': 'completed', 'video': {'url': 'https://cdn.example/video.mp4'}})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    p = HiggsfieldProvider('test:secret')
    step = await p.submit(UGC_MODEL, {})
    assert step == {'request_id': rid}
    assert (await p.status(step))['status'] == 'COMPLETED'
    await p.cancel(step)
    p.request = AsyncMock(return_value={'status': 'failed', 'error': 'secret details'})
    with pytest.raises(ProviderError) as e: await p.status(step)
    assert 'secret details' not in str(e.value)


@pytest.mark.parametrize('url', ['https://127.0.0.1/file', 'https://169.254.169.254/x', 'https://[::1]/x',
                                      'https://user:pass@cdn.example/x', 'http://cdn.example/x', 'https://cdn.example:444/x'])
def test_higgsfield_storage_rejects_unsafe_urls(url):
    with pytest.raises(ValueError): public_https(url)


async def test_ugc_planner_reviewable_scoped_and_metered(env, monkeypatch):
    from app.routers.production import PlanOut
    plan = PlanOut(title='مراجعة', scenes=[{'prompt': 'Show the product', 'duration': 10, 'spoken_text': 'شوف تفاصيل المنتج'}])
    call = AsyncMock(return_value=SimpleNamespace(parsed_output=plan, usage=SimpleNamespace(input_tokens=20, output_tokens=30)))
    monkeypatch.setattr(settings, 'anthropic_api_key', 'local-test')
    monkeypatch.setattr(llm, 'client', lambda: SimpleNamespace(messages=SimpleNamespace(parse=call)))
    request = {'brand_id': env['brand'], 'brief': 'اعلان للمنتج من غير اختراع فوائد', 'scene_count': 1}
    env['as_user']('viewer')
    assert (await env['api'].post('/api/production/plan', json=request)).status_code == 403
    env['as_user']('owner')
    result = await env['api'].post('/api/production/plan', json=request)
    assert result.status_code == 200 and result.json()['scenes'][0]['spoken_text']
    async with SessionLocal() as db:
        assert await db.scalar(select(ProductionJob)) is None
        assert (await db.scalar(select(UsageEvent))).operation == 'ugc_plan'
    monkeypatch.setattr(settings, 'production_daily_limit', 1)
    assert (await env['api'].post('/api/production/plan', json=request)).status_code == 429
