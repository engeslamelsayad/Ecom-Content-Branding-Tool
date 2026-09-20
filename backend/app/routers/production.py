from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..config import settings
from ..deps import DbDep, UserDep, get_brand, require_owner
from ..fal_provider import FalProvider, ProviderError, IMAGE_MODEL, VIDEO_MODEL, AUDIO_MODEL
from ..integrations import cipher, fal_key
from ..models import Asset, Brand, Client, Integration, ProductionJob, Run, UsageEvent
from ..production import ACTIVE, make_steps, safe_asset_path

router = APIRouter(prefix='/api', tags=['production'])


class ConnectionIn(BaseModel):
    key: SecretStr = Field(min_length=10, max_length=500)


@router.get('/integrations/fal')
async def connection_status(db: DbDep, user: UserDep):
    # A member can see availability, never configuration or stored secrets.
    try:
        configured = bool(await fal_key(db))
    except ValueError:
        configured = False
    return {'configured': configured, 'provider': 'fal',
            'models': {'image': IMAGE_MODEL, 'video': VIDEO_MODEL, 'audio': AUDIO_MODEL},
            'daily_limit': settings.production_daily_limit,
            'max_active': settings.production_max_active}


@router.put('/integrations/fal')
async def save_connection(body: ConnectionIn, db: DbDep, user: UserDep):
    await require_owner(user)
    value = body.key.get_secret_value().strip()
    if len(value) < 10 or any(c.isspace() for c in value):
        raise HTTPException(422, 'مفتاح API غير صالح.')
    row = await db.get(Integration, 'fal')
    if not row:
        row = Integration(name='fal')
        db.add(row)
    row.encrypted_key = cipher().encrypt(value.encode()).decode()
    await db.commit()
    return {'configured': True}


@router.post('/integrations/fal/check')
async def check_connection(db: DbDep, user: UserDep):
    await require_owner(user)
    key = await fal_key(db)
    if not key:
        raise HTTPException(409, 'أضف المفتاح أولًا.')
    try:
        return await FalProvider(key).check()
    except ProviderError as exc:
        raise HTTPException(502, str(exc)) from None


class SceneIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    prompt: str = Field(min_length=5, max_length=2300)
    duration: Literal[5, 10] = 5


class ProductionIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    brand_id: str
    idempotency_key: str = Field(min_length=8, max_length=80)
    title: str = Field(default='', max_length=200)
    kind: Literal['image', 'video', 'audio']
    prompt: str = Field(default='', max_length=5000)
    source_run_id: str | None = None
    reference_asset_id: str | None = None
    aspect_ratio: Literal['1:1', '9:16', '16:9'] = '9:16'
    voiceover: str = Field(default='', max_length=5000)
    voice: str = Field(default='Rachel', min_length=1, max_length=100)
    language: Literal['ar', 'en'] = 'ar'
    scenes: list[SceneIn] = Field(default_factory=list, max_length=6)
    confirmed: bool = False

    @model_validator(mode='after')
    def validate_content(self):
        if not self.confirmed:
            raise ValueError('راجع المحتوى ووافق على تكلفة المزود قبل الإنتاج.')
        if self.kind == 'audio' and not self.voiceover.strip():
            raise ValueError('اكتب النص المنطوق فقط.')
        if self.kind == 'image' and len(self.prompt.strip()) < 5:
            raise ValueError('اكتب وصف التصميم.')
        if self.kind == 'video' and not self.scenes:
            raise ValueError('أضف مشهدًا واحدًا على الأقل.')
        return self


def public_job(job):
    return {'id': job.id, 'kind': job.kind, 'title': job.title, 'status': job.status,
            'error': job.error, 'created_at': job.created_at.isoformat(),
            'asset_id': job.asset_id, 'completed_steps': sum(s.get('state') == 'done' for s in job.steps),
            'total_steps': len(job.steps), 'source_run_id': job.inputs.get('source_run_id'),
            'can_finalize': job.status == 'error' and all(s.get('state') == 'done' for s in job.steps)}


@router.post('/production', status_code=201)
async def create_production(body: ProductionIn, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, body.brand_id, need='editor')
    # Serialize reservations per client on Postgres, including across its brands.
    await db.scalar(select(Client).where(Client.id == brand.client_id).with_for_update())
    existing = await db.scalar(select(ProductionJob).where(
        ProductionJob.brand_id == brand.id, ProductionJob.idempotency_key == body.idempotency_key))
    if existing:
        return public_job(existing)
    if not await fal_key(db):
        raise HTTPException(409, 'الإنتاج غير متصل. اطلب من المالك إضافة مفتاح fal من الإعدادات.')
    if body.source_run_id:
        run = await db.get(Run, body.source_run_id)
        if not run or run.brand_id != brand.id:
            raise HTTPException(404, 'المصدر غير موجود في البراند.')
    if body.reference_asset_id:
        asset = await db.get(Asset, body.reference_asset_id)
        if not asset or asset.brand_id != brand.id or asset.kind != 'image':
            raise HTTPException(404, 'الصورة المرجعية غير موجودة في البراند.')
        safe_asset_path(asset)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    query = select(func.count()).select_from(ProductionJob).join(Brand).where(Brand.client_id == brand.client_id)
    active = await db.scalar(query.where(ProductionJob.status.in_(ACTIVE)))
    used = await db.scalar(query.where(ProductionJob.created_at >= today))
    if active >= settings.production_max_active or used >= settings.production_daily_limit:
        raise HTTPException(429, 'وصل الحساب لحد الإنتاج الجاري أو اليومي. انتظر اكتمال الطلبات أو تواصل مع المالك.')
    inputs = body.model_dump(exclude={'confirmed', 'idempotency_key', 'brand_id', 'kind', 'title'})
    # Only the relevant brand identity is shared, not the entire Brain/financial data.
    inputs['brand_brief'] = '\n'.join(filter(None, [brand.name, brand.one_liner,
        str((brand.core or {}).get('visual', ''))[:3000]]))
    job = ProductionJob(brand_id=brand.id, user_id=user.id, kind=body.kind,
                        title=body.title or {'image': 'تصميم', 'video': 'فيديو', 'audio': 'تعليق صوتي'}[body.kind],
                        idempotency_key=body.idempotency_key, inputs=inputs,
                        steps=make_steps(body.kind, inputs))
    db.add(job)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        job = await db.scalar(select(ProductionJob).where(ProductionJob.brand_id == body.brand_id,
                                                        ProductionJob.idempotency_key == body.idempotency_key))
        if not job:
            raise
    return public_job(job)


@router.get('/production')
async def list_production(brand_id: str, db: DbDep, user: UserDep, offset: int = 0):
    await get_brand(db, user, brand_id)
    query = select(ProductionJob).where(ProductionJob.brand_id == brand_id).order_by(ProductionJob.created_at.desc())
    return {'items': [public_job(j) for j in await db.scalars(query.offset(max(offset, 0)).limit(50))]}


@router.post('/production/{job_id}/cancel')
async def cancel_production(job_id: str, db: DbDep, user: UserDep):
    job = await db.get(ProductionJob, job_id)
    if not job:
        raise HTTPException(404, 'الطلب غير موجود.')
    await get_brand(db, user, job.brand_id, need='editor')
    if job.status not in ACTIVE:
        raise HTTPException(409, 'الطلب انتهى بالفعل.')
    job.cancel_requested = True
    await db.commit()
    return {'ok': True}


@router.get('/assets/{asset_id}/file')
async def asset_file(asset_id: str, db: DbDep, user: UserDep, download: bool = False):
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(404, 'الملف غير موجود.')
    await get_brand(db, user, asset.brand_id)
    return FileResponse(safe_asset_path(asset), media_type=asset.media_type,
                        filename=asset.filename if download else None,
                        headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff'})


@router.post('/production/{job_id}/finalize')
async def retry_finalization(job_id: str, db: DbDep, user: UserDep):
    job = await db.scalar(select(ProductionJob).where(ProductionJob.id == job_id).with_for_update())
    if not job:
        raise HTTPException(404, 'الطلب غير موجود.')
    await get_brand(db, user, job.brand_id, need='editor')
    if job.status != 'error' or not job.steps or not all(s.get('state') == 'done' for s in job.steps):
        raise HTTPException(409, 'إعادة التجميع متاحة فقط عند اكتمال كل ملفات المزود.')
    job.status, job.error = 'running', ''
    await db.commit()
    return {'ok': True}


@router.get('/brands/{brand_id}/usage')
async def usage(brand_id: str, db: DbDep, user: UserDep):
    await get_brand(db, user, brand_id)
    rows = list(await db.scalars(select(UsageEvent).where(UsageEvent.brand_id == brand_id)
                                .order_by(UsageEvent.created_at.desc()).limit(200)))
    return {'items': [{'operation': r.operation, 'provider': r.provider, 'model': r.model,
                       'cost_usd': r.cost_usd, 'units': r.units, 'created_at': r.created_at.isoformat()}
                      for r in rows],
            'note': 'تكلفة النص تقديرية من التوكنز. تكلفة fal غير متاحة هنا؛ الفاتورة الفعلية في حساب المزود.'}
