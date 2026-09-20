"""Clients, brands, and everything inside the Brand Brain."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from pydantic import ValidationError
from sqlalchemy import select

from ..deps import DbDep, UserDep, accessible_client_ids, get_brand, get_client, require_owner, client_role
from ..models import Avatar, Brand, Client, Competitor, CoreRevision, Membership, Product, VoCEntry

router = APIRouter(prefix="/api", tags=["workspace"])


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
class ClientIn(BaseModel):
    name: str
    notes: str = ""


@router.get("/clients")
async def list_clients(db: DbDep, user: UserDep):
    allowed = await accessible_client_ids(db, user)
    query = select(Client).order_by(Client.name)
    if allowed is not None:
        if not allowed:
            return []
        query = query.where(Client.id.in_(allowed))
    rows = await db.scalars(query)
    return [{"id": c.id, "name": c.name, "notes": c.notes} for c in rows]


@router.post("/clients", status_code=201)
async def create_client(payload: ClientIn, db: DbDep, user: UserDep):
    """Only an owner opens a new client; they then grant others access to it."""
    await require_owner(user)
    client = Client(**payload.model_dump())
    db.add(client)
    await db.flush()
    db.add(Membership(user_id=user.id, client_id=client.id, role="admin"))
    await db.commit()
    return {"id": client.id, "name": client.name, "notes": client.notes}


@router.patch("/clients/{client_id}")
async def update_client(client_id: str, payload: ClientIn, db: DbDep, user: UserDep):
    client = await get_client(db, user, client_id, need="admin")
    client.name, client.notes = payload.name, payload.notes
    await db.commit()
    return {"id": client.id, "name": client.name, "notes": client.notes}


@router.delete("/clients/{client_id}", status_code=204)
async def delete_client(client_id: str, db: DbDep, user: UserDep):
    await require_owner(user)
    client = await db.get(Client, client_id)
    if client is not None:
        await db.delete(client)
        await db.commit()


# ---------------------------------------------------------------------------
# Brands
# ---------------------------------------------------------------------------
class BrandIn(BaseModel):
    client_id: str
    name: str
    one_liner: str = ""
    industry: str = ""
    market: str = "EG"
    dialect: str = "مصري"
    stage: str = "launch"


class BrandPatch(BaseModel):
    name: str | None = None
    one_liner: str | None = None
    industry: str | None = None
    market: str | None = None
    dialect: str | None = None
    stage: str | None = None
    core: dict[str, Any] | None = None


def _brand_summary(brand: Brand) -> dict:
    return {
        "id": brand.id, "client_id": brand.client_id, "name": brand.name,
        "one_liner": brand.one_liner, "industry": brand.industry, "market": brand.market,
        "dialect": brand.dialect, "stage": brand.stage,
        "core_keys": sorted((brand.core or {}).keys()),
    }


@router.get("/brands")
async def list_brands(db: DbDep, user: UserDep, client_id: str | None = None):
    allowed = await accessible_client_ids(db, user)
    query = select(Brand).order_by(Brand.name)
    if allowed is not None:
        if not allowed:
            return []
        query = query.where(Brand.client_id.in_(allowed))
    if client_id:
        query = query.where(Brand.client_id == client_id)
    return [_brand_summary(b) for b in await db.scalars(query)]


@router.post("/brands", status_code=201)
async def create_brand(payload: BrandIn, db: DbDep, user: UserDep):
    await get_client(db, user, payload.client_id, need="admin")
    brand = Brand(**payload.model_dump(), core={})
    db.add(brand)
    await db.commit()
    return _brand_summary(brand)


@router.get("/brands/{brand_id}")
async def read_brand(brand_id: str, db: DbDep, user: UserDep):
    """The whole Brain — what every module inherits."""
    brand = await get_brand(db, user, brand_id)
    return {
        **_brand_summary(brand),
        'role': await client_role(db, user, brand.client_id),
        "core": brand.core or {},
        "products": [{
            "id": p.id, "name": p.name, "description": p.description, "usp": p.usp,
            "url": p.url, "price": p.price, "cost": p.cost, "currency": p.currency,
        } for p in brand.products],
        "avatars": [{"id": a.id, "name": a.name, "is_primary": a.is_primary, "data": a.data}
                    for a in brand.avatars],
        "competitors": [{"id": c.id, "name": c.name, "kind": c.kind, "data": c.data}
                        for c in brand.competitors],
        "voc": [{"id": v.id, "source": v.source, "category": v.category, "text": v.text}
                for v in brand.voc_entries],
    }


@router.patch("/brands/{brand_id}")
async def patch_brand(brand_id: str, payload: BrandPatch, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, brand_id, need="editor")
    if payload.core is not None:
        await get_client(db, user, brand.client_id, need='admin')
        brand = await db.scalar(select(Brand).where(Brand.id == brand_id).with_for_update())
        for key, value in (brand.core or {}).items():
            db.add(CoreRevision(brand_id=brand.id, key=key, value=str(value), user_id=user.id))
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(brand, key, value)
    await db.commit()
    return _brand_summary(brand)


@router.delete("/brands/{brand_id}", status_code=204)
async def delete_brand(brand_id: str, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, brand_id, need="admin")
    await db.delete(brand)
    await db.commit()


@router.delete("/brands/{brand_id}/core/{key}", status_code=204)
async def clear_core_key(brand_id: str, key: str, db: DbDep, user: UserDep):
    """Drop one established-strategy entry so a module can start clean."""
    brand = await get_brand(db, user, brand_id, need="admin")
    brand = await db.scalar(select(Brand).where(Brand.id == brand_id).with_for_update())
    core = dict(brand.core or {})
    if key in core:
        db.add(CoreRevision(brand_id=brand.id, key=key, value=str(core[key]), user_id=user.id))
    core.pop(key, None)
    brand.core = core
    await db.commit()


# ---------------------------------------------------------------------------
# Brain sub-resources
# ---------------------------------------------------------------------------
class ProductIn(BaseModel):
    name: str
    description: str = ""
    usp: str = ""
    url: str = ""
    price: float | None = None
    cost: float | None = None
    currency: str = "EGP"


class AvatarIn(BaseModel):
    name: str
    is_primary: bool = False
    data: dict[str, Any] = {}


class CompetitorIn(BaseModel):
    name: str
    kind: str = "direct"
    data: dict[str, Any] = {}


class VoCIn(BaseModel):
    text: str
    source: str = "review"
    category: str = "motivation"


_CHILDREN = {
    "products": (Product, ProductIn),
    "avatars": (Avatar, AvatarIn),
    "competitors": (Competitor, CompetitorIn),
    "voc": (VoCEntry, VoCIn),
}


@router.patch('/brands/{brand_id}/{resource}/{item_id}')
async def update_child(brand_id: str, resource: str, item_id: str, payload: dict, db: DbDep, user: UserDep):
    await get_brand(db, user, brand_id, need='editor')
    if resource not in _CHILDREN:
        raise HTTPException(404, 'نوع غير معروف')
    model, schema = _CHILDREN[resource]
    row = await db.get(model, item_id)
    if not row or row.brand_id != brand_id:
        raise HTTPException(404, 'العنصر غير موجود')
    current = {key: getattr(row, key) for key in schema.model_fields}
    try:
        values = schema(**{**current, **payload}).model_dump()
    except ValidationError:
        raise HTTPException(422, 'راجع بيانات العنصر.') from None
    for key, value in values.items():
        setattr(row, key, value)
    await db.commit()
    return {'id': row.id}


@router.post("/brands/{brand_id}/{resource}", status_code=201)
async def add_child(brand_id: str, resource: str, payload: dict, db: DbDep, user: UserDep):
    if resource not in _CHILDREN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نوع غير معروف")
    brand = await get_brand(db, user, brand_id, need="editor")
    model, schema = _CHILDREN[resource]
    row = model(brand_id=brand.id, **schema(**payload).model_dump())
    db.add(row)
    await db.commit()
    return {"id": row.id}


@router.delete("/brands/{brand_id}/{resource}/{item_id}", status_code=204)
async def delete_child(brand_id: str, resource: str, item_id: str, db: DbDep, user: UserDep):
    if resource not in _CHILDREN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "نوع غير معروف")
    await get_brand(db, user, brand_id, need="editor")
    model, _ = _CHILDREN[resource]
    row = await db.get(model, item_id)
    if row is not None and row.brand_id == brand_id:
        await db.delete(row)
        await db.commit()


class VoCBulkIn(BaseModel):
    """Paste a wall of reviews at once — the fast path to a real VoC bank."""
    text: str
    source: str = "review"
    category: str = "motivation"
    separator: str = "\n"


@router.post("/brands/{brand_id}/voc/bulk", status_code=201)
async def bulk_voc(brand_id: str, payload: VoCBulkIn, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, brand_id, need="editor")
    lines = [line.strip() for line in payload.text.split(payload.separator)]
    added = [VoCEntry(brand_id=brand.id, text=line, source=payload.source,
                      category=payload.category) for line in lines if len(line) > 3]
    db.add_all(added)
    await db.commit()
    return {"added": len(added)}
