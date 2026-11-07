import pytest

from app import assist as assist_engine
from app.config import settings
from app.db import SessionLocal
from app.llm import Usage
from app.models import Run
from app.modules import ALL_MODULES, MAX_CHOICES, get_module
from app.prompting import build_task

AUDIENCE = {'angle_generator', 'hooks', 'ad_script', 'ugc_script', 'voiceover', 'landing_copy',
            'ad_copy', 'email_sms', 'review_static', 'review_landing', 'review_video'}
NOUR, KARIM, OMAR = 'نور، 27 سنة: عندها قطتين', 'كريم، 38 سنة: مدخن', 'عمر، 24 سنة: طالب'


@pytest.fixture(autouse=True)
def roomy_queue(monkeypatch):
    # These tests queue several runs; keep the per-client concurrency cap out of the way.
    monkeypatch.setattr(settings, 'max_concurrent_runs', 50)


def test_every_audience_tool_offers_the_same_multi_choice_avatar_field():
    with_avatar = {m.key for m in ALL_MODULES for f in m.fields if f.name == 'avatar'}
    assert with_avatar == AUDIENCE
    for key in AUDIENCE:
        field = next(f for f in get_module(key).fields if f.name == 'avatar')
        assert field.type == 'multiselect' and field.assist == 'extract'


async def test_catalogue_carries_the_cap(env):
    modules = (await env['api'].get('/api/catalog')).json()['modules']
    ugc = next(m for m in modules if m['key'] == 'ugc_script')
    assert next(f for f in ugc['fields'] if f['name'] == 'avatar')['max'] == MAX_CHOICES


async def seed(api, brand):
    await api.post(f'/api/brands/{brand}/products', json={'name': 'ERASE'})
    for name in (NOUR, KARIM, OMAR):
        await api.post(f'/api/brands/{brand}/avatars', json={'name': name})


async def start(api, brand, avatar, key='ugc_script'):
    return await api.post('/api/runs', json={
        'brand_id': brand, 'module_key': key, 'inputs': {'product': 'ERASE', 'avatar': avatar}})


async def test_run_creation_normalises_and_bounds_the_choice(env):
    api, brand = env['api'], env['brand']
    await seed(api, brand)

    response = await start(api, brand, [f' {NOUR} ', KARIM, NOUR])
    assert response.status_code == 201
    async with SessionLocal() as db:
        run = await db.get(Run, response.json()['id'])
    assert run.inputs['avatar'] == [NOUR, KARIM]  # trimmed, de-duplicated, order kept

    response = await start(api, brand, OMAR)  # a bare string still works
    async with SessionLocal() as db:
        assert (await db.get(Run, response.json()['id'])).inputs['avatar'] == [OMAR]

    assert (await start(api, brand, ['شخص مش موجود'])).status_code == 422
    assert (await start(api, brand, [NOUR, 3])).status_code == 422
    assert (await start(api, brand, {'name': NOUR})).status_code == 422


async def test_more_than_the_cap_is_refused(env):
    api, brand = env['api'], env['brand']
    await api.post(f'/api/brands/{brand}/products', json={'name': 'ERASE'})
    names = [f'أفاتار {i}' for i in range(MAX_CHOICES + 1)]
    for name in names:
        await api.post(f'/api/brands/{brand}/avatars', json={'name': name})
    assert (await start(api, brand, names[:MAX_CHOICES])).status_code == 201
    assert (await start(api, brand, names)).status_code == 422


def test_several_avatars_each_get_their_own_piece_in_the_prompt():
    ugc = get_module('ugc_script')
    task = build_task(ugc, {'avatar': [NOUR, KARIM]})
    assert f'**avatar**: {NOUR}، {KARIM}' in task  # names, not a JSON blob
    assert '## Target avatars' in task and 'own hook, objection and proof' in task
    assert 'one script per named avatar' in ugc.instructions

    assert '## Target avatars' not in build_task(ugc, {'avatar': [NOUR]})
    review = build_task(get_module('review_video'), {'avatar': [NOUR, KARIM]})
    assert 'fit score per avatar' in review and 'own hook' not in review


async def test_an_empty_choice_is_offered_to_the_assistant(env, monkeypatch):
    api, brand = env['api'], env['brand']
    await seed(api, brand)
    asked = []

    async def suggest(module, brand_row, names, current=None):
        asked.extend(names)
        return [], Usage()
    monkeypatch.setattr(assist_engine, 'suggest', suggest)
    response = await api.post('/api/assist/fields', json={
        'brand_id': brand, 'module_key': 'ugc_script', 'inputs': {'product': 'ERASE', 'avatar': []}})
    assert response.status_code == 200
    assert 'avatar' in asked and 'product' not in asked
