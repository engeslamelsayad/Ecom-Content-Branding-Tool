from sqlalchemy import select

from app import llm, runner
from app.db import SessionLocal
from app.models import Brand, CoreRevision, RunWorkflow
from app.modules import CONTENT_MODULES, PRODUCT_GUIDELINES, get_module


def stream_text(text, seen=None):
    async def generate(request):
        if seen is not None:
            seen.append(request)
        yield llm.Chunk('text', text)
        yield llm.Chunk('usage', usage=llm.Usage(model='claude-opus-5', input_tokens=10, output_tokens=5))
    return generate


async def add_product(api, brand, name):
    response = await api.post(f'/api/brands/{brand}/products', json={'name': name, 'usp': 'تركيز 15%'})
    assert response.status_code == 201
    return response.json()['id']


async def generate_guidelines(env, monkeypatch, product, text):
    monkeypatch.setattr(llm, 'stream', stream_text(text))
    response = await env['api'].post('/api/runs', json={
        'brand_id': env['brand'], 'module_key': 'product_guidelines', 'inputs': {'product': product}})
    assert response.status_code == 201, response.text
    rid = response.json()['id']
    await runner.execute(rid)
    return rid


async def approve(api, rid):
    version = (await api.get(f'/api/runs/{rid}/workflow')).json()['version']
    return await api.patch(f'/api/runs/{rid}/workflow', json={'status': 'approved', 'version': version})


async def guidelines(brand_id):
    async with SessionLocal() as db:
        return (await db.get(Brand, brand_id)).core.get(PRODUCT_GUIDELINES, {})


def test_guidelines_lead_the_content_tab_and_protect_evidence():
    assert CONTENT_MODULES[0].key == 'product_guidelines'
    module = get_module('product_guidelines')
    assert module.writes_product == PRODUCT_GUIDELINES and not module.writes_core
    policies = {f.name: f.assist for f in module.fields}
    assert policies['approved_claims'] == 'none'
    assert policies['must_say'] == 'draft' and policies['product'] == 'extract'
    assert 'awareness stage' in module.instructions and 'ممنوع يتقال' in module.instructions


async def test_guidelines_need_a_product_that_exists_in_the_brain(env):
    api = env['api']
    await add_product(api, env['brand'], 'Glow Serum')
    for inputs in ({}, {'product': 'منتج مش موجود'}):
        response = await api.post('/api/runs', json={
            'brand_id': env['brand'], 'module_key': 'product_guidelines', 'inputs': inputs})
        assert response.status_code == 422


async def test_approval_saves_guidelines_per_product_without_overwriting(env, monkeypatch):
    api = env['api']
    glow = await add_product(api, env['brand'], 'Glow Serum')
    night = await add_product(api, env['brand'], 'Night Repair')

    first = await generate_guidelines(env, monkeypatch, 'Glow Serum', 'GLOW v1')
    assert await guidelines(env['brand']) == {}  # a draft never reaches the Brain
    workflow = (await api.get(f'/api/runs/{first}/workflow')).json()
    assert workflow['writes_core'] == 'إرشادات Glow Serum'
    assert (await approve(api, first)).status_code == 200

    second = await generate_guidelines(env, monkeypatch, 'Night Repair', 'NIGHT v1')
    assert (await approve(api, second)).status_code == 200
    saved = await guidelines(env['brand'])
    assert saved[glow]['content'] == 'GLOW v1' and saved[night]['content'] == 'NIGHT v1'

    third = await generate_guidelines(env, monkeypatch, 'Glow Serum', 'GLOW v2')
    assert (await approve(api, third)).status_code == 200
    saved = await guidelines(env['brand'])
    assert saved[glow] == {'product': 'Glow Serum', 'content': 'GLOW v2', 'run_id': third}
    assert saved[night]['content'] == 'NIGHT v1'
    async with SessionLocal() as db:
        history = (await db.scalars(select(CoreRevision.value).where(
            CoreRevision.key == f'{PRODUCT_GUIDELINES}:Glow Serum'))).all()
    assert 'GLOW v1' in history and 'GLOW v2' in history


async def test_approved_guidelines_bind_later_content_for_that_product(env, monkeypatch):
    api = env['api']
    await add_product(api, env['brand'], 'Glow Serum')
    rid = await generate_guidelines(env, monkeypatch, 'Glow Serum', '⛔ مانقولش إنه بيعالج')
    assert (await approve(api, rid)).status_code == 200

    seen = []
    monkeypatch.setattr(llm, 'stream', stream_text('سكريبت', seen))
    response = await api.post('/api/runs', json={
        'brand_id': env['brand'], 'module_key': 'ugc_script', 'inputs': {'product': 'Glow Serum'}})
    await runner.execute(response.json()['id'])
    context = seen[0].context_text
    assert 'Approved product guidelines' in context
    assert '### Glow Serum\n⛔ مانقولش إنه بيعالج' in context
    assert 'Established strategy' not in context  # guidelines alone are not "strategy"
    assert 'Product guidelines are binding' in context
    assert 'التزام بالإرشادات' in get_module('review_video').instructions

    # Alongside real strategy, guidelines still stay out of the generic dump,
    # where they would otherwise appear as a raw JSON blob.
    async with SessionLocal() as db:
        brand = await db.get(Brand, env['brand'])
        brand.core = {**brand.core, 'positioning': 'POSITIONING TEXT'}
        await db.commit()
    seen.clear()
    response = await api.post('/api/runs', json={
        'brand_id': env['brand'], 'module_key': 'ugc_script', 'inputs': {'product': 'Glow Serum'}})
    await runner.execute(response.json()['id'])
    context = seen[0].context_text
    assert '### positioning\nPOSITIONING TEXT' in context
    assert f'### {PRODUCT_GUIDELINES}' not in context and '"content"' not in context
    assert context.count('مانقولش إنه بيعالج') == 1

    # Another product, or none, never carries Glow's brief.
    await add_product(api, env['brand'], 'Night Repair')
    for inputs in ({'product': 'Night Repair'}, {}):
        seen.clear()
        response = await api.post('/api/runs', json={
            'brand_id': env['brand'], 'module_key': 'hooks', 'inputs': inputs})
        await runner.execute(response.json()['id'])
        assert 'مانقولش إنه بيعالج' not in seen[0].context_text
        assert 'Approved product guidelines' not in seen[0].context_text


async def test_product_name_is_normalised_so_approval_matches(env, monkeypatch):
    api = env['api']
    glow = await add_product(api, env['brand'], 'Glow Serum')
    rid = await generate_guidelines(env, monkeypatch, '  Glow Serum ', 'GLOW')
    assert (await approve(api, rid)).status_code == 200
    assert (await guidelines(env['brand']))[glow]['content'] == 'GLOW'


async def test_renamed_product_blocks_approval_and_changes_nothing(env, monkeypatch):
    api = env['api']
    glow = await add_product(api, env['brand'], 'Glow Serum')
    rid = await generate_guidelines(env, monkeypatch, 'Glow Serum', 'GLOW')
    await api.patch(f"/api/brands/{env['brand']}/products/{glow}", json={'name': 'Glow Serum 2'})
    response = await approve(api, rid)
    assert response.status_code == 409
    assert await guidelines(env['brand']) == {}
    async with SessionLocal() as db:
        assert (await db.get(RunWorkflow, rid)).status == 'draft'


async def test_guidelines_are_cleared_per_product_and_with_the_product(env, monkeypatch):
    api = env['api']
    glow = await add_product(api, env['brand'], 'Glow Serum')
    night = await add_product(api, env['brand'], 'Night Repair')
    for name in ('Glow Serum', 'Night Repair'):
        assert (await approve(api, await generate_guidelines(env, monkeypatch, name, name))).status_code == 200

    env['as_user']('editor')
    response = await api.delete(f"/api/brands/{env['brand']}/core/product_guidelines/{night}")
    assert response.status_code == 403
    env['as_user']('owner')

    assert (await api.delete(f"/api/brands/{env['brand']}/products/{glow}")).status_code == 204
    assert set(await guidelines(env['brand'])) == {night}

    response = await api.delete(f"/api/brands/{env['brand']}/core/product_guidelines/{night}")
    assert response.status_code == 204
    async with SessionLocal() as db:
        assert PRODUCT_GUIDELINES not in (await db.get(Brand, env['brand'])).core
