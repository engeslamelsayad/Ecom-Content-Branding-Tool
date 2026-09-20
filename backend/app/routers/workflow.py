"""Editable, versioned outputs and explicit approval into Brand Brain."""
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .. import runner
from ..config import settings
from ..deps import DbDep, UserDep, get_brand
from ..models import Brand, Campaign, Client, CoreRevision, Run, RunComment, RunRevision, RunWorkflow
from ..modules import get_module

router = APIRouter(prefix='/api', tags=['workflow'])


async def checked_run(db, user, run_id, need='viewer', lock=False):
    query = select(Run).where(Run.id == run_id)
    run = await db.scalar(query.with_for_update() if lock else query)
    if not run:
        raise HTTPException(404, 'المخرج غير موجود.')
    await get_brand(db, user, run.brand_id, need=need)
    return run


async def flow(db, run):
    record = await db.get(RunWorkflow, run.id)
    if not record:
        record = RunWorkflow(run_id=run.id, version=1, status='draft')
        db.add(record)
        await db.flush()
    return record


@router.get('/runs/{run_id}/workflow')
async def get_workflow(run_id: str, db: DbDep, user: UserDep):
    run = await checked_run(db, user, run_id)
    record = await db.get(RunWorkflow, run.id)
    revisions = await db.scalars(select(RunRevision).where(RunRevision.run_id == run.id).order_by(RunRevision.created_at.desc()).limit(30))
    comments = await db.scalars(select(RunComment).where(RunComment.run_id == run.id).order_by(RunComment.created_at).limit(200))
    return {'status': record.status if record else 'draft', 'version': record.version if record else 1,
            'writes_core': get_module(run.module_key).writes_core if not run.parent_run_id else '',
            'revisions': [{'id': r.id, 'output_md': r.output_md, 'note': r.note, 'created_at': r.created_at.isoformat()} for r in revisions],
            'comments': [{'author': c.author, 'text': c.text, 'created_at': c.created_at.isoformat()} for c in comments]}


class EditIn(BaseModel):
    output_md: str = Field(min_length=1, max_length=250000)
    version: int = Field(ge=1)


@router.patch('/runs/{run_id}/output')
async def edit_output(run_id: str, body: EditIn, db: DbDep, user: UserDep):
    run = await checked_run(db, user, run_id, 'editor', lock=True)
    if await db.scalar(select(Run.id).where(Run.parent_run_id == run.id, Run.status.in_(['queued', 'running']))):
        raise HTTPException(409, 'انتظر انتهاء إعادة توليد القسم قبل تعديل الخطة.')
    if run.status in ('running', 'queued'):
        raise HTTPException(409, 'انتظر انتهاء التوليد قبل التعديل.')
    record = await flow(db, run)
    if record.version != body.version:
        raise HTTPException(409, 'اتعدّل المخرج من مستخدم آخر. أعد فتحه قبل حفظ تعديلاتك.')
    db.add(RunRevision(run_id=run.id, user_id=user.id, output_md=run.output_md, note='قبل التعديل اليدوي'))
    run.output_md = body.output_md
    record.version += 1
    record.status = 'draft'
    # Manual changes invalidate the AI score; do not show a stale review score.
    run.scores = {}
    await db.commit()
    return {'version': record.version}


class StatusIn(BaseModel):
    status: Literal['draft', 'internal_review', 'client_review', 'approved']
    version: int = Field(ge=1)


@router.patch('/runs/{run_id}/workflow')
async def set_status(run_id: str, body: StatusIn, db: DbDep, user: UserDep):
    run = await checked_run(db, user, run_id, 'admin' if body.status == 'approved' else 'editor', lock=True)
    if await db.scalar(select(Run.id).where(Run.parent_run_id == run.id, Run.status.in_(['queued', 'running']))):
        raise HTTPException(409, 'انتظر انتهاء إعادة توليد القسم قبل اعتماد الخطة.')
    if run.status != 'done':
        raise HTTPException(409, 'الاعتماد والمراجعة متاحان بعد اكتمال المخرج.')
    record = await flow(db, run)
    if record.version != body.version:
        raise HTTPException(409, 'تغيّر المخرج. حدّث الصفحة قبل اعتماده.')
    record.status, record.version = body.status, record.version + 1
    module = get_module(run.module_key)
    if body.status == 'approved' and module.writes_core and not run.parent_run_id:
        brand = await db.scalar(select(Brand).where(Brand.id == run.brand_id).with_for_update())
        core = dict(brand.core or {})
        if module.writes_core in core:
            db.add(CoreRevision(brand_id=brand.id, key=module.writes_core,
                                value=str(core[module.writes_core]), user_id=user.id))
        core[module.writes_core] = run.output_md
        brand.core = core
        db.add(CoreRevision(brand_id=brand.id, key=module.writes_core, value=run.output_md,
                            source_run_id=run.id, user_id=user.id))
    await db.commit()
    return {'status': record.status, 'version': record.version}


class CommentIn(BaseModel):
    text: str = Field(min_length=1, max_length=3000)


@router.post('/runs/{run_id}/comments', status_code=201)
async def comment(run_id: str, body: CommentIn, db: DbDep, user: UserDep):
    await checked_run(db, user, run_id)
    db.add(RunComment(run_id=run_id, author=user.name or user.email, text=body.text))
    await db.commit()
    return {'ok': True}


@router.post('/runs/{run_id}/cancel')
async def cancel_run(run_id: str, db: DbDep, user: UserDep):
    run = await checked_run(db, user, run_id, 'editor')
    if run.status not in ('queued', 'running'):
        raise HTTPException(409, 'التشغيل انتهى بالفعل.')
    await runner.cancel(run_id)
    await db.refresh(run)
    if run.status in ('queued', 'running'):
        run.status, run.error = 'interrupted', 'أوقف المستخدم الطلب قبل بدء التوليد.'
        await db.commit()
    return {'ok': True}


@router.post('/runs/{run_id}/resume')
async def resume_run(run_id: str, db: DbDep, user: UserDep):
    run = await checked_run(db, user, run_id, 'editor', lock=True)
    if run.status not in ('error', 'interrupted') or run_id in runner._tasks:
        raise HTTPException(409, 'هذا التشغيل غير قابل للاستكمال الآن.')
    brand = await get_brand(db, user, run.brand_id, need='editor')
    await db.scalar(select(Client).where(Client.id == brand.client_id).with_for_update())
    active = await db.scalar(select(func.count()).select_from(Run).join(Brand).where(
        Brand.client_id == brand.client_id, Run.status.in_(['queued', 'running'])))
    if active >= settings.max_concurrent_runs:
        raise HTTPException(429, 'انتظر انتهاء تشغيل جارٍ قبل الاستكمال.')
    if run.output_md:
        db.add(RunRevision(run_id=run.id, output_md=run.output_md, user_id=user.id, note='قبل الاستكمال'))
    run.status, run.error = 'queued', ''
    await db.commit()
    runner.start(run.id)
    return {'id': run.id}


class CampaignIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    brief: dict = Field(default_factory=dict)
    run_ids: list[str] = Field(default_factory=list, max_length=100)
    stage: Literal['brief', 'angles', 'copy', 'production', 'review', 'done'] = 'brief'


@router.get('/brands/{brand_id}/campaigns')
async def campaigns(brand_id: str, db: DbDep, user: UserDep):
    await get_brand(db, user, brand_id)
    rows = await db.scalars(select(Campaign).where(Campaign.brand_id == brand_id).order_by(Campaign.updated_at.desc()).limit(100))
    return [{'id': c.id, 'title': c.title, 'brief': c.brief, 'run_ids': c.run_ids, 'stage': c.stage} for c in rows]


async def validate_campaign_runs(db, brand_id, ids):
    if ids:
        owned = set(await db.scalars(select(Run.id).where(Run.brand_id == brand_id, Run.id.in_(ids))))
        if owned != set(ids):
            raise HTTPException(404, 'أحد المخرجات لا ينتمي للبراند.')


@router.post('/brands/{brand_id}/campaigns', status_code=201)
async def create_campaign(brand_id: str, body: CampaignIn, db: DbDep, user: UserDep):
    await get_brand(db, user, brand_id, need='editor')
    await validate_campaign_runs(db, brand_id, body.run_ids)
    row = Campaign(brand_id=brand_id, **body.model_dump())
    db.add(row)
    await db.commit()
    return {'id': row.id}


@router.put('/brands/{brand_id}/campaigns/{campaign_id}')
async def update_campaign(brand_id: str, campaign_id: str, body: CampaignIn, db: DbDep, user: UserDep):
    await get_brand(db, user, brand_id, need='editor')
    row = await db.get(Campaign, campaign_id)
    if not row or row.brand_id != brand_id:
        raise HTTPException(404, 'الحملة غير موجودة.')
    await validate_campaign_runs(db, brand_id, body.run_ids)
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    await db.commit()
    return {'ok': True}
