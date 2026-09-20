import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image
from sqlalchemy import select, func

from app import production
from app.config import settings
from app.db import SessionLocal
from app.fal_provider import FalProvider, ProviderError, queue_url
from app.integrations import fal_key
from app.models import Asset, Integration, ProductionJob, UsageEvent
from app.public_fetch import PublicResolver, install_public_routes


def request(env, **kw):
    return dict(brand_id=env['brand'], idempotency_key='unique-job-0001', kind='image',
                prompt='Product packshot', confirmed=True, **kw)


async def test_encrypted_connection_owner_only_and_never_returned(env):
    api = env['api']
    secret = 'test-secret-key-123456789'
    env['as_user']('editor')
    assert (await api.put('/api/integrations/fal', json={'key': secret})).status_code == 403
    env['as_user']('owner')
    assert (await api.put('/api/integrations/fal', json={'key': secret})).status_code == 200
    async with SessionLocal() as db:
        row = await db.get(Integration, 'fal')
        assert secret not in row.encrypted_key
        assert await fal_key(db) == secret
    env['as_user']('viewer')
    response = await api.get('/api/integrations/fal')
    assert response.json()['configured'] and secret not in response.text


async def test_idempotency_limits_reference_validation_and_tenant_access(env):
    api = env['api']
    body = request(env)
    first = await api.post('/api/production', json=body)
    assert first.status_code == 201
    again = await api.post('/api/production', json=body)
    assert again.json()['id'] == first.json()['id']
    rejected = await api.post('/api/production', json={**body, 'idempotency_key': 'other-0002', 'confirmed': False})
    assert rejected.status_code == 422
    assert (await api.post('/api/production', json={**body, 'idempotency_key': 'other-0002', 'reference_asset_id': 'missing'})).status_code == 404
    assert (await api.post('/api/production', json={**body, 'idempotency_key': 'other-0002'})).status_code == 201
    assert (await api.post('/api/production', json={**body, 'idempotency_key': 'other-0003'})).status_code == 429
    env['as_user']('viewer')
    assert (await api.post('/api/production', json=body)).status_code == 403
    env['as_user']('other')
    assert (await api.post(f"/api/production/{first.json()['id']}/cancel")).status_code == 403
    assert (await api.get('/api/production', params={'brand_id': env['brand']})).status_code == 403


async def test_durable_queue_download_and_authenticated_asset(env, monkeypatch):
    provider = SimpleNamespace(submit=AsyncMock(return_value={'request_id': 'provider-id', 'status_url': 'status', 'response_url': 'result', 'cancel_url': 'cancel'}),
                               status=AsyncMock(return_value={'status': 'COMPLETED'}),
                               result=AsyncMock(return_value={'images': [{'url': 'https://v3.fal.media/output.png'}]}))
    monkeypatch.setattr(production, 'FalProvider', lambda key: provider)
    async def download(url, path):
        Image.new('RGB', (16, 16), 'blue').save(path)
    monkeypatch.setattr(production, 'download', download)
    api = env['api']
    job_id = (await api.post('/api/production', json=request(env))).json()['id']
    await production.tick(job_id)
    # Each tick opens a fresh DB session: provider ID survives worker/process restart.
    async with SessionLocal() as db:
        assert (await db.get(ProductionJob, job_id)).steps[0]['request_id'] == 'provider-id'
    await production.tick(job_id)
    await production.tick(job_id)
    await production.tick(job_id)
    assert provider.submit.await_count == 1
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, job_id)
        assert job.status == 'done'
        asset_id = job.asset_id
        assert await db.scalar(select(func.count()).select_from(UsageEvent)) == 1
    response = await api.get(f'/api/assets/{asset_id}/file?download=true')
    assert response.status_code == 200 and response.content.startswith(b'\x89PNG')
    assert response.headers['cache-control'] == 'private, no-store'
    env['as_user']('other')
    assert (await api.get(f'/api/assets/{asset_id}/file')).status_code == 403


async def test_uncertain_submission_is_never_repeated(env, monkeypatch):
    provider = SimpleNamespace(submit=AsyncMock(side_effect=httpx.ReadTimeout('timeout')))
    monkeypatch.setattr(production, 'FalProvider', lambda key: provider)
    job_id = (await env['api'].post('/api/production', json=request(env))).json()['id']
    with pytest.raises(httpx.ReadTimeout):
        await production.tick(job_id)
    await production.tick(job_id)
    await production.tick(job_id)
    async with SessionLocal() as db:
        assert (await db.get(ProductionJob, job_id)).status == 'needs_attention'
    assert provider.submit.await_count == 1
    assert (await env['api'].post(f'/api/production/{job_id}/finalize')).status_code == 409


async def test_cancel_prevents_submissions(env, monkeypatch):
    provider = SimpleNamespace(submit=AsyncMock())
    monkeypatch.setattr(production, 'FalProvider', lambda key: provider)
    job_id = (await env['api'].post('/api/production', json=request(env))).json()['id']
    assert (await env['api'].post(f'/api/production/{job_id}/cancel')).status_code == 200
    await production.tick(job_id)
    assert provider.submit.await_count == 0
    async with SessionLocal() as db:
        assert (await db.get(ProductionJob, job_id)).status == 'cancelled'


async def test_provider_protocol_and_secret_safe_errors(monkeypatch):
    real_client = httpx.AsyncClient
    def handler(req):
        assert req.headers['authorization'] == 'Key local-test-key'
        if req.method == 'POST':
            return httpx.Response(200, json={'request_id': '123', 'status_url': 'https://queue.fal.run/fal-ai/model/requests/123/status',
                                            'response_url': 'https://queue.fal.run/fal-ai/model/requests/123',
                                            'cancel_url': 'https://queue.fal.run/fal-ai/model/requests/123/cancel'})
        return httpx.Response(402, text='provider body with local-test-key')
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw))
    provider = FalProvider('local-test-key')
    step = await provider.submit('fal-ai/test-model', {'prompt': 'test'})
    assert step['request_id'] == '123'
    with pytest.raises(ProviderError) as err:
        await provider.status(step)
    assert 'local-test-key' not in str(err.value)


async def test_reference_photo_uses_edit_model_and_audio_is_spoken_text_only(env):
    buf = BytesIO(); Image.new('RGB', (16, 16), 'red').save(buf, format='PNG')
    asset = (await env['api'].post(f"/api/brands/{env['brand']}/assets", files={'file': ('photo.png', buf.getvalue(), 'image/png')}, data={'kind': 'image'})).json()
    body = request(env, reference_asset_id=asset['id'])
    response = await env['api'].post('/api/production', json=body)
    assert response.status_code == 201
    async with SessionLocal() as db:
        job = await db.get(ProductionJob, response.json()['id'])
        assert job.steps[0]['model'].endswith('/edit')
    payload = production.payload_for({'kind': 'audio'}, {'voiceover': 'الكلام المنطوق', 'voice': 'Rachel', 'language': 'ar', 'brand_brief': 'private strategy'})
    assert payload['text'] == 'الكلام المنطوق' and 'private' not in str(payload)


@pytest.mark.parametrize('url', ['http://fal.media/x', 'https://fal.media.evil.com/x', 'https://user:secret@fal.media/x', 'http://127.0.0.1', 'https://storage.googleapis.com:81/x'])
def test_provider_media_allowlist(url):
    with pytest.raises(ValueError):
        production.media_url(url)


def test_queue_rejects_credential_exfiltration():
    for url in ('https://evil.com/fal-ai/a', 'https://queue.fal.run.evil.com/fal-ai/a', 'https://queue.fal.run:443/fal-ai/a'):
        with pytest.raises(ValueError):
            queue_url(url)


async def test_browser_blocks_private_subresources_and_dns_rebinding(monkeypatch):
    page = SimpleNamespace(route=AsyncMock(), route_web_socket=AsyncMock())
    await install_public_routes(page)
    intercept = page.route.call_args.args[1]
    route = SimpleNamespace(request=SimpleNamespace(url='http://169.254.169.254/latest/meta-data', method='GET', resource_type='image'), abort=AsyncMock())
    await intercept(route)
    route.abort.assert_awaited_once()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, 'getaddrinfo', AsyncMock(return_value=[(2, 1, 6, '', ('127.0.0.1', 80))]))
    with pytest.raises(OSError):
        await PublicResolver().resolve('public-looking.example', 80)
