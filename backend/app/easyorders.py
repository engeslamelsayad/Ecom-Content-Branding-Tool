"""Read-only EasyOrders catalog import. Never persist or forward the API key."""
from collections import OrderedDict
import hashlib
import ipaddress
import math
import time
from urllib.parse import urlparse
from uuid import NAMESPACE_URL, uuid5

from bs4 import BeautifulSoup
import httpx
from pydantic import BaseModel, ConfigDict, Field

PRODUCTS_URL = 'https://api.easy-orders.net/api/v1/external-apps/products'
PAGE_SIZE = 50
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_last_requests = OrderedDict()


class CatalogError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def reserve_request(key):
    # The app runs one worker. Stay below the documented 40 requests/minute.
    digest = hashlib.sha256(key.encode()).hexdigest()
    now = time.monotonic()
    if now - _last_requests.get(digest, -100) < 1.6:
        raise CatalogError('استنى ثانيتين قبل طلب صفحة جديدة من EasyOrders.', 429)
    _last_requests[digest] = now
    _last_requests.move_to_end(digest)
    while len(_last_requests) > 1024:
        _last_requests.popitem(last=False)


def plain(value, limit=12000):
    soup = BeautifulSoup(str(value or '')[:100000], 'html.parser')
    for node in soup(['script', 'style', 'iframe', 'noscript']):
        node.decompose()
    return soup.get_text(' ', strip=True)[:limit]


def money(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 <= number <= 1e12 else None
    except (ValueError, TypeError):
        return None


def image_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        return ''
    try:
        parsed = urlparse(value)
        if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password:
            if parsed.port not in (None, 443) or parsed.hostname == 'localhost' or parsed.hostname.endswith(('.local', '.internal', '.localhost')):
                return ''
            try:
                ip = ipaddress.ip_address(parsed.hostname)
                if not ip.is_global or ip.is_multicast or ip.is_reserved:
                    return ''
            except ValueError:
                pass
            return value
    except ValueError:
        pass
    return ''


class Variant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    label: str = Field(default='', max_length=500)
    price: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    sale_price: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    quantity: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)


class CatalogProduct(BaseModel):
    model_config = ConfigDict(extra='forbid')
    external_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=12000)
    sku: str = Field(default='', max_length=200)
    slug: str = Field(default='', max_length=300)
    price: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    sale_price: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    quantity: float | None = Field(default=None, ge=0, le=1e12, allow_inf_nan=False)
    images: list[str] = Field(default_factory=list, max_length=30)
    categories: list[str] = Field(default_factory=list, max_length=50)
    options: list[str] = Field(default_factory=list, max_length=50)
    variants: list[Variant] = Field(default_factory=list, max_length=500)

    @property
    def selling_price(self):
        return self.sale_price if self.sale_price and (self.price is None or self.sale_price < self.price) else self.price


def normalize(raw):
    if not isinstance(raw, dict) or not raw.get('id') or not plain(raw.get('name'), 200):
        return None
    images = list(dict.fromkeys(filter(None, [image_url(raw.get('thumb'))] +
                    [image_url(x) for x in (raw.get('images') or [])[:30]])))[:30]
    variants = []
    for v in (raw.get('variants') or raw.get('Variants') or [])[:500]:
        variants.append(Variant(label=plain(' / '.join(
            str(p.get('variation', '')) + ': ' + str(p.get('variation_prop', ''))
            for p in (v.get('variation_props') or v.get('VariationProps') or [])), 500),
            price=money(v.get('price')), sale_price=money(v.get('sale_price')), quantity=money(v.get('quantity'))))
    options = []
    for v in (raw.get('variations') or raw.get('Variations') or [])[:50]:
        options.append(plain(str(v.get('name', '')) + ': ' + ', '.join(
            str(p.get('name') or p.get('value') or '') for p in (v.get('props') or v.get('Props') or [])), 1000))
    return CatalogProduct(external_id=str(raw['id'])[:200], name=plain(raw['name'], 200),
        description=plain(raw.get('description')), sku=plain(raw.get('sku'), 200),
        slug=plain(raw.get('slug'), 300), price=money(raw.get('price')), sale_price=money(raw.get('sale_price')),
        quantity=money(raw.get('quantity')) if raw.get('track_stock') else None,
        images=images, categories=[plain(c.get('name'), 200) for c in (raw.get('categories') or [])[:50] if c.get('name')],
        options=options, variants=variants)


def product_id(brand_id, external_id):
    return uuid5(NAMESPACE_URL, f'easyorders:{brand_id}:{external_id}').hex


async def fetch_page(key, page):
    reserve_request(key)
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False) as client:
            async with client.stream('GET', PRODUCTS_URL, headers={'Api-Key': key, 'Accept': 'application/json'},
                params={'page': page, 'limit': PAGE_SIZE, 'sort': 'id,ASC',
                        'join': 'Variations.Props,Variants.VariationProps'}) as response:
                if response.status_code in (401, 403):
                    raise CatalogError('راجع مفتاح EasyOrders وتأكد إنه مفعّل وعنده صلاحية الوصول إلى المنتجات (products:read).', 400)
                if response.status_code == 429:
                    raise CatalogError('وصلت لحد طلبات EasyOrders. انتظر دقيقة وجرب تاني.', 429)
                if response.status_code != 200:
                    raise CatalogError('تعذّر سحب المنتجات من EasyOrders الآن. جرّب مرة تانية لاحقًا.')
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > MAX_RESPONSE_BYTES:
                        raise CatalogError('صفحة المنتجات أكبر من الحد المسموح. تواصل مع الدعم.')
                import json
                result = json.loads(chunks)
    except CatalogError:
        raise
    except (httpx.HTTPError, ValueError):
        # Never include upstream bodies, headers, URLs or credentials in errors.
        raise CatalogError('تعذّر الاتصال بـEasyOrders أو قراءة الرد. جرّب مرة تانية.') from None
    rows = result if isinstance(result, list) else result.get('data') if isinstance(result, dict) else None
    if not isinstance(rows, list) or len(rows) > PAGE_SIZE:
        raise CatalogError('صيغة قائمة المنتجات من EasyOrders غير متوقعة. لم يتم حفظ أي بيانات.')
    products, skipped, seen = [], 0, set()
    try:
        for row in rows:
            product = normalize(row)
            if product is None or product.external_id in seen:
                skipped += 1
                continue
            seen.add(product.external_id)
            products.append(product)
    except (TypeError, ValueError, AttributeError):
        raise CatalogError('بعض بيانات المنتجات غير صالحة. لم يتم حفظ أي بيانات.') from None
    # Plain arrays have no total; request until an empty page (even if server caps below 50).
    has_more, total = bool(rows), None
    if isinstance(result, dict):
        total = result.get('total')
        if not isinstance(total, int) or isinstance(total, bool) or total < 0:
            total = None
        pages = result.get('pageCount')
        if isinstance(pages, int) and not isinstance(pages, bool):
            has_more = bool(rows) and page < pages
    return products, has_more, total, skipped
