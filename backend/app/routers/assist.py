"""Form assistance: propose field values, and seed a Brand Brain from a source."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from .. import assist as engine
from ..deps import DbDep, UserDep, get_brand
from ..media import fetch_page_text
from ..modules import get_module

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/assist", tags=["assist"])


class SuggestIn(BaseModel):
    brand_id: str
    module_key: str
    fields: list[str] = []          # empty means every assistable field
    inputs: dict = {}


@router.post("/fields")
async def suggest_fields(payload: SuggestIn, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, payload.brand_id, need="editor")
    module = get_module(payload.module_key)

    names = payload.fields or [
        f.name for f in module.fields
        if f.type != "file" and not str(payload.inputs.get(f.name, "")).strip()
    ]
    if not names:
        return {"suggestions": [], "cost_usd": 0.0}

    try:
        suggestions, usage = await engine.suggest(module, brand, names, payload.inputs)
    except Exception as exc:
        log.exception("field assist failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"تعذّر توليد الاقتراحات: {exc}") from exc

    return {
        "suggestions": [s.model_dump() for s in suggestions],
        "cost_usd": round(usage.cost_usd, 5),
    }


class BootstrapIn(BaseModel):
    brand_id: str
    url: str = ""
    text: str = ""


@router.post("/bootstrap")
async def bootstrap(payload: BootstrapIn, db: DbDep, user: UserDep):
    """Read a website or a written description into a reviewable brand profile.

    Nothing is saved here — the operator reviews and applies it.
    """
    brand = await get_brand(db, user, payload.brand_id, need="editor")

    source_text, label = payload.text.strip(), "وصف كتبه صاحب البراند"
    if payload.url.strip():
        try:
            title, source_text = await fetch_page_text(payload.url.strip())
            label = f"الموقع: {title or payload.url}"
        except Exception as exc:
            log.exception("bootstrap fetch failed")
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                f"تعذّر فتح الرابط: {exc}") from exc

    if len(source_text) < 40:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "المصدر قصير جدًا — حط رابط الموقع أو فقرة تشرح البراند.")

    try:
        profile, usage = await engine.bootstrap(brand, source_text, label)
    except Exception as exc:
        log.exception("bootstrap extraction failed")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY,
                            f"تعذّر استخراج البيانات: {exc}") from exc

    return {"profile": profile.model_dump(), "source": label,
            "cost_usd": round(usage.cost_usd, 5)}


class ApplyIn(BaseModel):
    brand_id: str
    profile: dict


@router.post("/bootstrap/apply", status_code=201)
async def apply_bootstrap(payload: ApplyIn, db: DbDep, user: UserDep):
    """Persist the parts of an extracted profile the operator kept."""
    from ..models import Avatar, Competitor, Product, VoCEntry

    brand = await get_brand(db, user, payload.brand_id, need="editor")
    profile = payload.profile or {}
    added = {"products": 0, "competitors": 0, "avatars": 0, "voc": 0}

    for key in ("one_liner", "industry", "market", "dialect"):
        if value := str(profile.get(key) or "").strip():
            setattr(brand, key, value)

    for item in profile.get("products") or []:
        if name := str(item.get("name") or "").strip():
            db.add(Product(
                brand_id=brand.id, name=name,
                description=item.get("description") or "", usp=item.get("usp") or "",
                price=item.get("price"), currency=item.get("currency") or "EGP",
            ))
            added["products"] += 1

    for item in profile.get("competitors") or []:
        if name := str(item.get("name") or "").strip():
            db.add(Competitor(brand_id=brand.id, name=name, kind="direct", data={
                k: v for k, v in item.items() if k != "name" and v}))
            added["competitors"] += 1

    for item in profile.get("avatars") or []:
        if name := str(item.get("name") or "").strip():
            db.add(Avatar(brand_id=brand.id, name=name, is_primary=added["avatars"] == 0, data={
                k: v for k, v in item.items() if k != "name" and v}))
            added["avatars"] += 1

    for quote in profile.get("voc") or []:
        if text := str(quote or "").strip():
            db.add(VoCEntry(brand_id=brand.id, text=text, source="website", category="motivation"))
            added["voc"] += 1

    await db.commit()
    return {"added": added}
