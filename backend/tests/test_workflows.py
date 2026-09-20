import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app import llm, runner
from app.calculators import EconomicsInput, compute
from app.db import SessionLocal
from app.models import Brand, Run, RunRevision, UsageEvent


async def fake_stream(request):
    yield llm.Chunk('text', request.task.split('## Section to produce now')[-1][:150])
    yield llm.Chunk('usage', usage=llm.Usage(model='claude-sonnet-5', input_tokens=10, output_tokens=5))


async def test_loss_making_calculator_and_arabic_export(env):
    api = env['api']
    response = await api.post('/api/tools/unit-economics', json={'aov': 100, 'cogs': 110})
    assert response.status_code == 200
    assert response.json()['breakeven_roas'] is None
    json.dumps(compute(EconomicsInput(aov=100, cogs=110)).to_dict(), allow_nan=False)
    async with SessionLocal() as db:
        run = Run(brand_id=env['brand'], module_key='hooks', status='done', output_md='## إعلان عربي')
        db.add(run); await db.commit(); rid = run.id
    result = await api.get(f'/api/runs/{rid}/export?format=md')
    assert result.status_code == 200 and "filename*=UTF-8''" in result.headers['content-disposition']


async def test_plan_prior_context_approval_and_regeneration(env, monkeypatch):
    requests = []
    async def generate(request):
        requests.append(request)
        async for chunk in fake_stream(request):
            yield chunk
    monkeypatch.setattr(llm, 'stream', generate)
    api = env['api']
    r = await api.post('/api/runs', json={'brand_id': env['brand'], 'module_key': 'full_plan', 'inputs': {'objective': 'اختبار'}})
    assert r.status_code == 201
    rid = r.json()['id']
    await runner.execute(rid)
    assert len(requests) == 13
    assert 'Earlier completed sections' not in requests[0].context_text
    assert 'Earlier completed sections' in requests[1].context_text
    assert 'Module 1' in requests[1].context_text
    async with SessionLocal() as db:
        brand = await db.get(Brand, env['brand']); assert not brand.core
        full = (await db.get(Run, rid)).output_md
        assert full.count('<!--section:') == 13
    approved = await api.patch(f'/api/runs/{rid}/workflow', json={'status': 'approved', 'version': 1})
    assert approved.status_code == 200
    r = await api.post(f'/api/runs/{rid}/sections/m07_stpd')
    assert r.status_code == 201
    await runner.execute(r.json()['id'])
    async with SessionLocal() as db:
        assert (await db.get(Brand, env['brand'])).core['plan'] == full
        assert (await db.get(Run, rid)).output_md.count('<!--section:') == 13
        assert await db.scalar(select(RunRevision).where(RunRevision.run_id == rid))
    workflow = (await api.get(f'/api/runs/{rid}/workflow')).json()
    assert workflow['status'] == 'draft'


async def test_edit_conflicts_comments_and_tenant_permissions(env):
    async with SessionLocal() as db:
        run = Run(brand_id=env['brand'], module_key='hooks', status='done', output_md='Original')
        db.add(run); await db.commit(); rid = run.id
    api = env['api']
    env['as_user']('viewer')
    assert (await api.patch(f'/api/runs/{rid}/output', json={'output_md': 'bad', 'version': 1})).status_code == 403
    assert (await api.post(f'/api/runs/{rid}/comments', json={'text': 'راجع الهوك'})).status_code == 201
    env['as_user']('editor')
    assert (await api.patch(f'/api/runs/{rid}/output', json={'output_md': 'Edited', 'version': 1})).status_code == 200
    assert (await api.patch(f'/api/runs/{rid}/output', json={'output_md': 'Stale', 'version': 1})).status_code == 409
    assert (await api.patch(f'/api/runs/{rid}/workflow', json={'status': 'approved', 'version': 2})).status_code == 403
    env['as_user']('other')
    assert (await api.get(f'/api/runs/{rid}/workflow')).status_code == 403
    assert (await api.get(f'/api/runs/{rid}/export?format=md')).status_code == 403


async def test_untrusted_inputs_rejected_before_launch(env):
    api = env['api']
    for inputs in ({'_image_path': '/private/image.png'}, {'unknown': 'field'}):
        r = await api.post('/api/runs', json={'brand_id': env['brand'], 'module_key': 'hooks', 'inputs': inputs})
        assert r.status_code == 422
    r = await api.post('/api/runs', json={'brand_id': env['brand'], 'module_key': 'review_landing', 'inputs': {'url': 'http://127.0.0.1'}})
    assert r.status_code == 422
    r = await api.post('/api/runs', json={'brand_id': env['brand'], 'module_key': 'review_static', 'inputs': {}})
    assert r.status_code == 422


async def test_recovery_and_remaining_sections_only(env, monkeypatch):
    async with SessionLocal() as db:
        run = Run(brand_id=env['brand'], module_key='full_plan', status='running',
                  output_md='<!--section:m01_summary-->SAVED\n<!--section:m02_swot-->partial',
                  inputs={'objective': 'test', '_completed_sections': ['m01_summary']})
        db.add(run); await db.commit(); rid = run.id
    await runner.recover()
    assert (await env['api'].get(f'/api/runs/{rid}')).json()['status'] == 'interrupted'
    reqs = []
    async def generate(req):
        reqs.append(req)
        async for chunk in fake_stream(req): yield chunk
    monkeypatch.setattr(llm, 'stream', generate)
    await runner.execute(rid)
    assert len(reqs) == 12
    result = (await env['api'].get(f'/api/runs/{rid}')).json()
    assert result['output_md'].startswith('<!--section:m01_summary-->SAVED')
    assert 'partial' not in result['output_md']
    assert result['output_md'].count('<!--section:') == 13


async def test_search_full_body_beyond_preview(env):
    async with SessionLocal() as db:
        db.add(Run(brand_id=env['brand'], module_key='hooks', status='done', output_md='x' * 300 + 'needle'))
        await db.commit()
    data = (await env['api'].get(f"/api/runs?brand_id={env['brand']}&q=needle")).json()
    assert data['total'] == 1


async def test_product_edit_and_campaign_brand_boundary(env):
    api = env['api']
    p = (await api.post(f"/api/brands/{env['brand']}/products", json={'name': 'A', 'price': 0})).json()
    assert (await api.patch(f"/api/brands/{env['brand']}/products/{p['id']}", json={'price': 200})).status_code == 200
    assert (await api.patch(f"/api/brands/{env['other_brand']}/products/{p['id']}", json={'price': 999})).status_code == 404
    async with SessionLocal() as db:
        foreign = Run(brand_id=env['other_brand'], module_key='hooks')
        db.add(foreign); await db.commit(); rid = foreign.id
    r = await api.post(f"/api/brands/{env['brand']}/campaigns", json={'title': 'C', 'run_ids': [rid]})
    assert r.status_code == 404
