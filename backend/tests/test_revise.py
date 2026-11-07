import pytest
from sqlalchemy import select

from app import llm, runner
from app.config import settings
from app.db import SessionLocal
from app.models import Run, RunRevision, RunWorkflow, UsageEvent

ORIGINAL = '## الهوكات\n| # | الهوك |\n|---|---|\n| 1 | ريحة بيتك إيه دي؟ |'


@pytest.fixture(autouse=True)
def no_background(monkeypatch):
    monkeypatch.setattr(runner, 'start_revision', lambda *a, **k: None)
    monkeypatch.setattr(settings, 'max_concurrent_runs', 50)


async def finished_run(brand, text=ORIGINAL, *, module='hooks', parent=None, status='done'):
    async with SessionLocal() as db:
        run = Run(brand_id=brand, module_key=module, title='هوكات', status=status,
                  output_md=text, parent_run_id=parent)
        db.add(run)
        await db.flush()
        db.add(RunWorkflow(run_id=run.id, status='approved', version=3))
        await db.commit()
        return run.id


def model_returns(monkeypatch, text, stop='end_turn', seen=None):
    async def stream(request):
        if seen is not None:
            seen.append(request)
        yield llm.Chunk('text', text)
        yield llm.Chunk('usage', usage=llm.Usage(model=request.model, input_tokens=100, output_tokens=40),
                        stop_reason=stop)
    monkeypatch.setattr(llm, 'stream', stream)


async def state(rid):
    async with SessionLocal() as db:
        run = await db.get(Run, rid)
        flow = await db.get(RunWorkflow, rid)
        revisions = (await db.scalars(select(RunRevision).where(RunRevision.run_id == rid))).all()
        usage = (await db.scalars(select(UsageEvent).where(
            UsageEvent.reference_id == rid, UsageEvent.operation == 'text_revision'))).all()
        return run, flow, revisions, usage


async def test_a_request_revises_the_output_into_a_new_draft_version(env, monkeypatch):
    api, rid = env['api'], await finished_run(env['brand'])
    response = await api.post(f'/api/runs/{rid}/revise',
                              json={'instruction': 'خلّي الجدول عمود واحد بس', 'version': 3})
    assert response.status_code == 202 and response.json()['status'] == 'revising'

    seen = []
    model_returns(monkeypatch, '## الهوكات\n- ريحة بيتك إيه دي؟', seen=seen)
    await runner.revise(rid, 'خلّي الجدول عمود واحد بس', env['users']['owner'])

    task = seen[0].task
    assert 'خلّي الجدول عمود واحد بس' in task and 'ريحة بيتك إيه دي؟ |' in task
    assert 'complete revised deliverable' in task
    run, flow, revisions, usage = await state(rid)
    assert run.status == 'done' and run.output_md == '## الهوكات\n- ريحة بيتك إيه دي؟'
    assert (flow.status, flow.version) == ('draft', 4)  # approval is not carried over
    assert [r.output_md for r in revisions] == [ORIGINAL]
    assert revisions[0].note.startswith('قبل التعديل بالـ AI: خلّي الجدول')
    assert len(usage) == 1 and usage[0].cost_usd > 0


async def test_a_cut_off_rewrite_never_replaces_the_original(env, monkeypatch):
    rid = await finished_run(env['brand'])
    async with SessionLocal() as db:
        (await db.get(Run, rid)).status = 'revising'
        await db.commit()
    model_returns(monkeypatch, '## الهوكات\n| # |', stop='max_tokens')
    await runner.revise(rid, 'طوّلها', None)
    run, flow, revisions, usage = await state(rid)
    assert run.status == 'done' and run.output_md == ORIGINAL
    assert flow.version == 3 and revisions == []
    assert len(usage) == 1  # the tokens were still spent


async def test_section_markers_must_survive_the_rewrite(env, monkeypatch):
    plan = '<!--section:m01-->\nملخص\n<!--section:m02-->\nSWOT'
    rid = await finished_run(env['brand'], plan, module='full_plan')
    model_returns(monkeypatch, 'ملخص وSWOT في قسم واحد')
    await runner.revise(rid, 'ادمجهم', None)
    assert (await state(rid))[0].output_md == plan

    model_returns(monkeypatch, '<!--section:m01-->\nملخص أقصر\n<!--section:m02-->\nSWOT')
    await runner.revise(rid, 'اختصر الملخص', None)
    assert (await state(rid))[0].output_md.startswith('<!--section:m01-->\nملخص أقصر')


async def test_a_revised_review_refreshes_its_scorecard(env, monkeypatch):
    rid = await finished_run(env['brand'], 'قديم\n```json\n{"total": 40}\n```', module='review_static')
    model_returns(monkeypatch, 'جديد\n```json\n{"total": 72}\n```')
    await runner.revise(rid, 'اكتب الحكم أوضح', None)
    assert (await state(rid))[0].scores == {'total': 72}


async def test_only_a_finished_complete_output_can_be_revised(env):
    api, brand = env['api'], env['brand']
    parent = await finished_run(brand)
    child = await finished_run(brand, parent=parent)
    running = await finished_run(brand, status='running')
    for rid in (child, running):
        response = await api.post(f'/api/runs/{rid}/revise', json={'instruction': 'عدّل', 'version': 3})
        assert response.status_code == 409
    stale = await api.post(f'/api/runs/{parent}/revise', json={'instruction': 'عدّل', 'version': 2})
    assert stale.status_code == 409
    env['as_user']('viewer')
    assert (await api.post(f'/api/runs/{parent}/revise',
                           json={'instruction': 'عدّل', 'version': 3})).status_code == 403


async def test_nothing_else_touches_an_output_while_it_is_being_revised(env):
    api, rid = env['api'], await finished_run(env['brand'])
    assert (await api.post(f'/api/runs/{rid}/revise',
                           json={'instruction': 'عدّل', 'version': 3})).status_code == 202
    assert (await api.patch(f'/api/runs/{rid}/output',
                            json={'output_md': 'يدوي', 'version': 3})).status_code == 409
    assert (await api.patch(f'/api/runs/{rid}/workflow',
                            json={'status': 'approved', 'version': 3})).status_code == 409
    assert (await api.delete(f'/api/runs/{rid}')).status_code == 409
    assert (await api.post(f'/api/runs/{rid}/revise',
                           json={'instruction': 'تاني', 'version': 3})).status_code == 409


async def test_a_restart_mid_revision_leaves_the_output_done_and_whole(env):
    rid = await finished_run(env['brand'])
    async with SessionLocal() as db:
        (await db.get(Run, rid)).status = 'revising'
        await db.commit()
    await runner.recover()
    run = (await state(rid))[0]
    assert run.status == 'done' and run.output_md == ORIGINAL and not run.error
