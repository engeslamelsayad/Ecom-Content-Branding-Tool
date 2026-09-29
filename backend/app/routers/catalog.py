"""Review and explicitly import an EasyOrders catalog into one authorized brand."""
from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select

from .. import easyorders
from ..deps import DbDep, UserDep, get_brand
from ..models import Brand, Product, ProductSource

router = APIRouter(prefix='/api/assist/easyorders', tags=['assist'])


class PreviewIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    brand_id: str
    api_key: SecretStr
    page: int = Field(default=1, ge=1, le=10000)


@router.post('/preview')
async def preview(body: PreviewIn, db: DbDep, user: UserDep, response: Response):
    brand = await get_brand(db, user, body.brand_id, need='editor')
    key = body.api_key.get_secret_value().strip()
    if not 10 <= len(key) <= 1000 or any(ord(c) < 33 or ord(c) > 126 for c in key):
        raise HTTPException(422, 'أدخل مفتاح Public API صالحًا من إعدادات EasyOrders.')
    try:
        products, has_more, total, skipped = await easyorders.fetch_page(key, body.page)
    except easyorders.CatalogError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    existing = {p.id for p in brand.products}
    response.headers['Cache-Control'] = 'no-store'
    return {'products': [dict(p.model_dump(), exists=easyorders.product_id(brand.id, p.external_id) in existing,
                             selling_price=p.selling_price) for p in products],
            'page': body.page, 'has_more': has_more, 'total': total, 'skipped': skipped}


class ApplyIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    brand_id: str
    currency: str = Field(pattern=r'^[A-Z]{3}$')
    products: list[easyorders.CatalogProduct] = Field(min_length=1, max_length=500)
    update_existing: bool = False


@router.post('/apply')
async def apply(body: ApplyIn, db: DbDep, user: UserDep):
    brand = await get_brand(db, user, body.brand_id, need='editor')
    # Serialize concurrent imports for a brand on Postgres. Deterministic IDs
    # also prevent duplicates after a dropped response or repeated apply.
    await db.scalar(select(Brand).where(Brand.id == brand.id).with_for_update())
    added = updated = skipped = 0
    seen = set()
    for item in body.products:
        local_id = easyorders.product_id(brand.id, item.external_id)
        if local_id in seen:
            skipped += 1
            continue
        seen.add(local_id)
        product = await db.get(Product, local_id)
        if product and not body.update_existing:
            skipped += 1
            continue
        if product:
            if product.brand_id != brand.id:
                raise HTTPException(409, 'تعارض في مرجع المنتج.')
            updated += 1
        else:
            product = Product(id=local_id, brand_id=brand.id)
            db.add(product)
            added += 1
        product.name = easyorders.plain(item.name, 200)
        product.description = easyorders.plain(item.description)
        product.price = item.selling_price
        product.currency = body.currency
        # Never overwrite local cost, USP or product URL when refreshing a catalog.
        await db.flush()
        source = await db.get(ProductSource, local_id)
        if not source:
            source = ProductSource(product_id=local_id, provider='easyorders', external_id=item.external_id)
            db.add(source)
        data = item.model_dump()
        data['images'] = list(filter(None, (easyorders.image_url(x) for x in item.images)))
        data['currency'] = body.currency
        source.data = data
    await db.commit()
    return {'added': added, 'updated': updated, 'skipped': skipped}
