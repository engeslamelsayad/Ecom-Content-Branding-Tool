"""The module catalogue, run execution, live streaming, library and export."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select, or_

from .. import exporters, runner
from ..config import settings
from ..deps import DbDep, UserDep, accessible_client_ids, get_brand
from ..llm import PRICING
from ..media import save_upload
from ..models import Asset, Brand, Client, Run, RunWorkflow
from ..modules import ALL_MODULES, get_module
from ..skill_engine import registry

router = APIRouter(prefix="/api", tags=["runs"])


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
@router.get("/catalog")
async def catalog(user: UserDep):
    """Everything the dashboard can run, grouped by tab."""
    return {
        "modules": [
            {
                "key": m.key, "tab": m.tab, "title": m.title, "subtitle": m.subtitle,
                "icon": m.icon, "kind": m.kind, "skill": m.skill, "command": m.command,
                "tier": m.tier, "sections": [{"key": k, "title": t} for k, t in m.sections],
                "fields": [{**asdict(f), "assist": f.assist} for f in m.fields],
            }
            for m in ALL_MODULES
        ],
        "models": [{"id": k, "input": v[0], "output": v[1]} for k, v in PRICING.items()],
        "defaults": {"deep": settings.model_deep, "fast": settings.model_fast},
        "skills": registry.available(),
    }


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------
@router.post("/brands/{brand_id}/assets", status_code=201)
async def upload_asset(brand_id: str, db: DbDep, user: UserDep,
                       file: UploadFile = File(...), kind: str = Form("image")):
    brand = await get_brand(db, user, brand_id, need="editor")
    if kind not in ('image', 'video', 'audio'):
        raise HTTPException(422, 'نوع الملف غير مدعوم.')
    limit = settings.max_upload_mb * 1024 * 1024
    payload = bytearray()
    while chunk := await file.read(1024 * 1024):
        payload.extend(chunk)
        if len(payload) > limit:
            raise HTTPException(413, f'الملف أكبر من الحد ({settings.max_upload_mb}MB)')
    if not payload:
        raise HTTPException(422, 'الملف فارغ.')
    if kind == 'image':
        from PIL import Image, UnidentifiedImageError
        from io import BytesIO
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
            raise HTTPException(422, 'ارفع صورة صالحة.') from None
    elif not (file.content_type or '').startswith(kind + '/'):
        raise HTTPException(422, 'نوع الملف لا يطابق المحتوى المطلوب.')

    path = save_upload(brand.id, file.filename or "upload", payload)
    asset = Asset(brand_id=brand.id, kind=kind, filename=file.filename or path.name,
                  path=str(path), media_type=file.content_type or "",
                  size_bytes=len(payload))
    db.add(asset)
    await db.commit()
    return {"id": asset.id, "filename": asset.filename, "size_bytes": asset.size_bytes}


# ---------------------------------------------------------------------------
# Runs
# ---------------------------------------------------------------------------
class RunIn(BaseModel):
    brand_id: str
    module_key: str
    inputs: dict = {}
    model: str | None = None


async def _resolve_asset(db, brand_id: str, asset_id: str, expected: str) -> str:
    """Client sends an asset id; the server decides the path. Never the reverse."""
    asset = await db.get(Asset, asset_id)
    if asset is None or asset.brand_id != brand_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "الملف غير موجود")
    if asset.kind != expected:
        raise HTTPException(422, 'نوع الملف غير مناسب للموديول.')
    from ..production import safe_asset_path
    safe_asset_path(asset)
    return asset.path


@router.post("/runs", status_code=201)
async def create_run(payload: RunIn, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, payload.brand_id, need="editor")
    try:
        module = get_module(payload.module_key)
    except KeyError:
        raise HTTPException(422, 'الموديول غير موجود.') from None
    if module.kind == "calculator":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "الموديول ده حاسبة مش تشغيلة")

    inputs = dict(payload.inputs)
    if any(k.startswith('_') for k in inputs):
        raise HTTPException(422, 'المدخلات الداخلية غير مسموحة.')
    allowed_fields = {f.name for f in module.fields} | {'image_asset_id', 'video_asset_id'}
    if set(inputs) - allowed_fields:
        raise HTTPException(422, 'يوجد حقل غير معروف.')
    if payload.model and payload.model not in PRICING:
        raise HTTPException(422, 'الموديل غير مدعوم.')
    await db.scalar(select(Client).where(Client.id == brand.client_id).with_for_update())
    active = await db.scalar(select(func.count()).select_from(Run).join(Brand).where(
        Brand.client_id == brand.client_id, Run.status.in_(['queued', 'running'])))
    if active >= settings.max_concurrent_runs:
        raise HTTPException(429, 'انتظر انتهاء تشغيل جارٍ قبل بدء تشغيل جديد.')
    for field_name, key, expected in (
        ("image_asset_id", "_image_path", "image"),
        ("video_asset_id", "_video_path", "video"),
    ):
        if asset_id := inputs.pop(field_name, None):
            inputs[key] = await _resolve_asset(db, brand.id, asset_id, expected)

    missing = [f.label for f in module.fields
               if f.required and f.type != "file" and not str(inputs.get(f.name, "")).strip()]
    if missing:
        raise HTTPException(422,
                            "حقول مطلوبة ناقصة: " + "، ".join(missing))
    if module.key == 'review_static' and not inputs.get('_image_path'):
        raise HTTPException(422, 'ارفع صورة الإعلان أولًا.')
    if module.key == 'review_video' and not inputs.get('_video_path'):
        raise HTTPException(422, 'ارفع الفيديو أولًا.')
    if inputs.get('url'):
        from ..media import assert_public_url, UnsafeURL
        try:
            await asyncio.to_thread(assert_public_url, inputs['url'])
        except (UnsafeURL, TypeError):
            raise HTTPException(422, 'الرابط يجب أن يشير إلى موقع عام.') from None
    inputs['_model_override'] = payload.model

    if not inputs.get("dialect"):
        inputs["dialect"] = brand.dialect

    run = Run(brand_id=brand.id, user_id=user.id, module_key=module.key,
              title=module.title, inputs=inputs, status="queued")
    db.add(run)
    await db.commit()

    runner.start(run.id, payload.model)
    return {"id": run.id, "status": run.status}


@router.post("/runs/{run_id}/sections/{section_key}", status_code=201)
async def regenerate_section(run_id: str, section_key: str, db: DbDep, user: UserDep,
                             model: str | None = None):
    """Re-run one section of a multi-part plan instead of the whole thing."""
    parent = await db.scalar(select(Run).where(Run.id == run_id).with_for_update())
    if parent is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التشغيلة غير موجودة")
    brand = await get_brand(db, user, parent.brand_id, need="editor")
    if model and model not in PRICING:
        raise HTTPException(422, 'الموديل غير مدعوم.')
    await db.scalar(select(Client).where(Client.id == brand.client_id).with_for_update())
    active = await db.scalar(select(func.count()).select_from(Run).join(Brand).where(
        Brand.client_id == brand.client_id, Run.status.in_(['queued', 'running'])))
    if active >= settings.max_concurrent_runs:
        raise HTTPException(429, 'انتظر انتهاء تشغيل جارٍ قبل إعادة التوليد.')
    if parent.status != 'done':
        raise HTTPException(409, 'انتظر اكتمال الخطة.')
    active_child = await db.scalar(select(Run.id).where(Run.parent_run_id == parent.id,
                                                     Run.status.in_(['queued', 'running'])))
    if active_child:
        raise HTTPException(409, 'يوجد قسم قيد التوليد. انتظر اكتماله.')

    module = get_module(parent.module_key)
    if section_key not in {k for k, _ in module.sections}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "القسم ده مش موجود في الموديول")

    child = Run(brand_id=parent.brand_id, user_id=user.id, module_key=parent.module_key,
                title=f"{parent.title} — {section_key}",
                inputs={k: v for k, v in (parent.inputs or {}).items() if k != '_completed_sections'},
                status="queued", parent_run_id=parent.id, section_key=section_key)
    db.add(child)
    child.inputs = {**child.inputs, '_model_override': model or child.inputs.get('_model_override')}
    await db.commit()

    runner.start(child.id, model)
    return {"id": child.id, "status": child.status}


@router.get("/runs")
async def list_runs(db: DbDep, user: UserDep, brand_id: str | None = None,
                    module_key: str | None = None, limit: int = 50, offset: int = 0, q: str = ''):
    allowed = await accessible_client_ids(db, user)
    query = select(Run).join(Brand, Brand.id == Run.brand_id).order_by(desc(Run.created_at))
    if allowed is not None:
        if not allowed:
            return {"items": [], "total": 0}
        query = query.where(Brand.client_id.in_(allowed))
    if brand_id:
        query = query.where(Run.brand_id == brand_id)
    if module_key:
        query = query.where(Run.module_key == module_key)
    if q.strip():
        pattern = '%' + q.strip().replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
        query = query.where(or_(Run.output_md.ilike(pattern, escape='\\'), Run.title.ilike(pattern, escape='\\')))

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    rows = list(await db.scalars(query.limit(max(1, min(limit, 200))).offset(max(0, offset))))
    workflows = {w.run_id: w.status for w in await db.scalars(
        select(RunWorkflow).where(RunWorkflow.run_id.in_([r.id for r in rows])))}
    return {
        "total": total or 0,
        "items": [{
            "id": r.id, "brand_id": r.brand_id, "module_key": r.module_key, "title": r.title,
            "status": r.status, "created_at": r.created_at.isoformat(), "model": r.model,
            "cost_usd": r.cost_usd, "scores": r.scores or {},
            "parent_run_id": r.parent_run_id, "section_key": r.section_key,
            "workflow": workflows.get(r.id, 'draft'),
            "preview": (r.output_md or "")[:180],
        } for r in rows],
    }


@router.get("/runs/{run_id}")
async def read_run(run_id: str, db: DbDep, user: UserDep):
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التشغيلة غير موجودة")
    await get_brand(db, user, run.brand_id)
    module = get_module(run.module_key)
    return {
        "id": run.id, "brand_id": run.brand_id, "module_key": run.module_key,
        "title": run.title, "status": run.status, "output_md": run.output_md,
        "error": run.error, "model": run.model, "cost_usd": run.cost_usd,
        "input_tokens": run.input_tokens, "output_tokens": run.output_tokens,
        "cache_read_tokens": run.cache_read_tokens, "scores": run.scores or {},
        "inputs": {k: v for k, v in (run.inputs or {}).items() if not k.startswith("_")},
        "created_at": run.created_at.isoformat(),
        "sections": [{"key": k, "title": t} for k, t in module.sections],
    }


@router.delete("/runs/{run_id}", status_code=204)
async def delete_run(run_id: str, db: DbDep, user: UserDep):
    run = await db.get(Run, run_id)
    if run is None:
        return
    await get_brand(db, user, run.brand_id, need="editor")
    if run.status in ('running', 'queued'):
        raise HTTPException(409, 'أوقف التشغيل قبل حذفه.')
    await db.delete(run)
    await db.commit()


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request, db: DbDep, user: UserDep):
    """Server-sent events. Late joiners get the backlog, then follow live."""
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التشغيلة غير موجودة")
    await get_brand(db, user, run.brand_id)

    stream = runner.broker.get(run_id)
    if stream is None:
        # Finished before this connection, or the process restarted: replay
        # whatever was persisted and close.
        async def replay():
            payload = {"type": "text", "text": run.output_md}
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            closing = {"type": "done" if run.status == "done" else "error",
                       "text": run.error, "cost": run.cost_usd}
            yield f"data: {json.dumps(closing, ensure_ascii=False)}\n\n"
            yield "data: {\"type\":\"end\"}\n\n"

        return StreamingResponse(replay(), media_type="text/event-stream")

    async def follow():
        queue: asyncio.Queue = asyncio.Queue()
        backlog = list(stream.chunks)
        stream.subscribers.add(queue)
        try:
            for event in backlog:
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            if stream.done:
                yield "data: {\"type\":\"end\"}\n\n"
                return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"   # keeps proxies from closing the connection
                    continue
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "end":
                    return
        finally:
            stream.subscribers.discard(queue)

    return StreamingResponse(follow(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive",
    })


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str, db: DbDep, user: UserDep, format: str = "docx"):
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "التشغيلة غير موجودة")
    brand = await get_brand(db, user, run.brand_id)
    if not run.output_md.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مفيش مخرجات للتصدير")

    module = get_module(run.module_key)
    stem = f"{brand.name}-{module.key}".replace(" ", "-")
    disposition = f"attachment; filename=\"{module.key}.{format}\"; filename*=UTF-8''{quote(stem + '.' + format)}"

    if format == "md":
        return Response(run.output_md, media_type="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": disposition})

    builder = {"docx": exporters.markdown_to_docx, "pdf": exporters.markdown_to_pdf}.get(format)
    if builder is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "صيغة غير مدعومة")

    data = await asyncio.to_thread(builder, run.output_md, module.title, brand.name, module.subtitle)
    media_type = ("application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  if format == "docx" else "application/pdf")
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": disposition})
