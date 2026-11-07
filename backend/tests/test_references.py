import pytest

from app import llm, runner
from app.config import settings
from app.db import SessionLocal
from app.models import Run, RunWorkflow
from app.modules import MAX_REFERENCE_CHARS, MAX_REFERENCES


@pytest.fixture(autouse=True)
def roomy_queue(monkeypatch):
    monkeypatch.setattr(settings, 'max_concurrent_runs', 50)


async def library_run(brand, text, *, workflow='approved', status='done', module='angle_generator',
                      parent=None, title='زوايا معتمدة'):
    async with SessionLocal() as db:
        run = Run(brand_id=brand, module_key=module, title=title, status=status,
                  output_md=text, parent_run_id=parent)
        db.add(run)
        await db.flush()
        db.add(RunWorkflow(run_id=run.id, status=workflow))
        await db.commit()
        return run.id


def capture(monkeypatch):
    seen = []

    async def stream(request):
        seen.append(request)
        yield llm.Chunk('text', 'مخرج')
        yield llm.Chunk('usage', usage=llm.Usage(model=request.model, input_tokens=1, output_tokens=1))
    monkeypatch.setattr(llm, 'stream', stream)
    return seen


async def start(api, brand, references, key='hooks'):
    return await api.post('/api/runs', json={
        'brand_id': brand, 'module_key': key, 'inputs': {'references': references}})


async def test_a_chosen_approved_output_reaches_the_model(env, monkeypatch):
    api, brand = env['api'], env['brand']
    ref = await library_run(brand, '<!--section:a-->\nزاوية «ضيوف فجأة» هي الأقوى')
    seen = capture(monkeypatch)

    response = await start(api, brand, [ref])
    assert response.status_code == 201, response.text
    await runner.execute(response.json()['id'])
    context = seen[0].context_text
    assert 'APPROVED REFERENCES CHOSEN FOR THIS RUN' in context
    assert 'زاوية «ضيوف فجأة» هي الأقوى' in context and '<!--section' not in context

    detail = (await api.get(f"/api/runs/{response.json()['id']}")).json()
    assert detail['references'] == [{'id': ref, 'title': 'زوايا معتمدة'}]
    assert '_references' not in detail['inputs']


async def test_without_a_choice_the_library_stays_out(env, monkeypatch):
    api, brand = env['api'], env['brand']
    await library_run(brand, 'مخرج معتمد مش مختار')
    seen = capture(monkeypatch)
    response = await api.post('/api/runs', json={'brand_id': brand, 'module_key': 'hooks', 'inputs': {}})
    await runner.execute(response.json()['id'])
    assert 'APPROVED REFERENCES' not in seen[0].context_text
    assert 'مخرج معتمد مش مختار' not in seen[0].context_text


async def test_only_approved_complete_outputs_of_this_brand_qualify(env):
    api, brand = env['api'], env['brand']
    draft = await library_run(brand, 'مسودة', workflow='draft')
    foreign = await library_run(env['other_brand'], 'براند تاني')
    parent = await library_run(brand, 'خطة')
    child = await library_run(brand, 'قسم', parent=parent)
    unfinished = await library_run(brand, 'لسه', status='running')
    for bad in ([draft], [foreign], [child], [unfinished], 'نص', [3]):
        assert (await start(api, brand, bad)).status_code == 422, bad
    # The server alone sets the internal key; a client cannot smuggle it in.
    response = await api.post('/api/runs', json={
        'brand_id': brand, 'module_key': 'hooks', 'inputs': {'_references': [parent]}})
    assert response.status_code == 422


async def test_the_count_and_total_size_are_bounded(env):
    api, brand = env['api'], env['brand']
    ids = [await library_run(brand, f'مرجع {i}') for i in range(MAX_REFERENCES + 1)]
    assert (await start(api, brand, ids[:MAX_REFERENCES])).status_code == 201
    assert (await start(api, brand, ids)).status_code == 422

    big = await library_run(brand, 'ك' * (MAX_REFERENCE_CHARS + 1))
    response = await start(api, brand, [big])
    assert response.status_code == 422 and 'طويلة' in response.json()['detail']


async def test_a_reference_unapproved_before_the_run_starts_is_dropped(env, monkeypatch):
    api, brand = env['api'], env['brand']
    ref = await library_run(brand, 'كان معتمد')
    response = await start(api, brand, [ref])
    async with SessionLocal() as db:
        (await db.get(RunWorkflow, ref)).status = 'draft'
        await db.commit()
    seen = capture(monkeypatch)
    await runner.execute(response.json()['id'])
    assert 'كان معتمد' not in seen[0].context_text


async def test_the_picker_lists_only_approved_complete_outputs_with_sizes(env):
    api, brand = env['api'], env['brand']
    good = await library_run(brand, 'معتمد')
    await library_run(brand, 'مسودة', workflow='draft')
    await library_run(brand, 'قسم', parent=good)
    items = (await api.get(f'/api/runs?brand_id={brand}&approved=true')).json()['items']
    assert [(i['id'], i['chars']) for i in items] == [(good, len('معتمد'))]
