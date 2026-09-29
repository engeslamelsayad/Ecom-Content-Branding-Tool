from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import select

from app import easyorders
from app.db import SessionLocal
from app.models import Product, ProductSource, Integration

HTTP_CLIENT = httpx.AsyncClient


def sample():
    return {'id': 'product-uuid-1', 'name': 'تيشيرت', 'description': '<p>قطن أصلي</p><script>steal()</script>',
        'price': 250, 'sale_price': 199, 'sku': 'TS-1', 'slug': 'shirt',
        'thumb': 'https://cdn.example.com/shirt.jpg', 'images': ['javascript:alert(1)', 'https://cdn.example.com/shirt.jpg'],
        'track_stock': True, 'quantity': 7, 'categories': [{'id': 'c1', 'name': 'ملابس'}],
        'Variations': [{'name': 'المقاس', 'Props': [{'name': 'M'}, {'name': 'L'}]}],
        'Variants': [{'price': 250, 'sale_price': 0, 'quantity': 3,
                      'VariationProps': [{'variation': 'المقاس', 'variation_prop': 'M'}]}]}


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(easyorders.httpx, 'AsyncClient',
        lambda **kwargs: HTTP_CLIENT(transport=httpx.MockTransport(handler), **kwargs))
    easyorders._last_requests.clear()


async def test_protocol_pagination_and_normalization(monkeypatch):
    def handler(request):
        assert request.method == 'GET'
        assert str(request.url).startswith(easyorders.PRODUCTS_URL + '?')
        assert request.headers['Api-Key'] == 'test-secret-only'
        assert 'Authorization' not in request.headers
        assert request.url.params['page'] == '2'
        assert request.url.params['limit'] == '50'
        assert request.url.params['join'] == 'Variations.Props,Variants.VariationProps'
        return httpx.Response(200, json={'data': [sample()], 'total': 51, 'pageCount': 2})
    mock_http(monkeypatch, handler)
    products, more, total, skipped = await easyorders.fetch_page('test-secret-only', 2)
    p = products[0]
    assert not more and total == 51 and skipped == 0
    assert p.description == 'قطن أصلي' and p.selling_price == 199
    assert p.images == ['https://cdn.example.com/shirt.jpg']
    assert p.options == ['المقاس: M, L'] and p.variants[0].label == 'المقاس: M'
    assert p.quantity == 7 and p.categories == ['ملابس']


@pytest.mark.parametrize('status', [401, 403, 429, 500, 302])
async def test_provider_errors_never_echo_key_or_follow_redirect(monkeypatch, status):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, text='test-secret-only', headers={'Location': 'https://evil.example/key'})
    mock_http(monkeypatch, handler)
    with pytest.raises(easyorders.CatalogError) as error:
        await easyorders.fetch_page('test-secret-only', 1)
    assert 'test-secret-only' not in str(error.value) and len(calls) == 1
    assert error.value.status == (429 if status == 429 else 400 if status in (401, 403) else 502)


async def test_arrays_empty_pages_and_missing_identity(monkeypatch):
    responses = [[sample(), sample(), {'name': 'missing id'}], []]
    mock_http(monkeypatch, lambda request: httpx.Response(200, json=responses.pop(0)))
    products, more, total, skipped = await easyorders.fetch_page('test-secret-only', 1)
    assert len(products) == 1 and more and total is None and skipped == 2
    easyorders._last_requests.clear()
    products, more, _, _ = await easyorders.fetch_page('test-secret-only', 2)
    assert products == [] and not more


async def test_invalid_shape_size_timeout_and_throttling(monkeypatch):
    mock_http(monkeypatch, lambda request: httpx.Response(200, json={'unexpected': 'secret'}))
    with pytest.raises(easyorders.CatalogError):
        await easyorders.fetch_page('test-secret-only', 1)
    with pytest.raises(easyorders.CatalogError) as error:
        await easyorders.fetch_page('test-secret-only', 2)
    assert error.value.status == 429
    monkeypatch.setattr(easyorders, 'MAX_RESPONSE_BYTES', 10)
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=b'x' * 11))
    with pytest.raises(easyorders.CatalogError):
        await easyorders.fetch_page('test-secret-only', 1)
    def fail(request):
        raise httpx.ReadTimeout('test-secret-only', request=request)
    mock_http(monkeypatch, fail)
    with pytest.raises(easyorders.CatalogError) as error:
        await easyorders.fetch_page('test-secret-only', 1)
    assert 'test-secret-only' not in str(error.value)


async def test_preview_and_apply_permissions_no_secrets_saved(env, monkeypatch):
    fetch = AsyncMock(return_value=([easyorders.normalize(sample())], False, 1, 0))
    monkeypatch.setattr(easyorders, 'fetch_page', fetch)
    api = env['api']
    body = {'brand_id': env['brand'], 'api_key': 'test-secret-only'}
    for role in ('viewer', 'other'):
        env['as_user'](role)
        assert (await api.post('/api/assist/easyorders/preview', json=body)).status_code == 403
        assert (await api.post('/api/assist/easyorders/apply', json={'brand_id': env['brand'],
            'currency': 'EGP', 'products': [easyorders.normalize(sample()).model_dump()]})).status_code == 403
    fetch.assert_not_called()
    env['as_user']('editor')
    r = await api.post('/api/assist/easyorders/preview', json=body)
    assert r.status_code == 200 and r.headers['Cache-Control'] == 'no-store'
    assert 'test-secret-only' not in r.text and not r.json()['products'][0]['exists']
    async with SessionLocal() as db:
        assert list(await db.scalars(select(Product))) == []
        assert list(await db.scalars(select(Integration))) == []
    assert (await api.post('/api/assist/easyorders/preview', json=dict(body, api_key='bad secret'))).status_code == 422


async def test_apply_idempotent_update_preserves_local_fields_and_brand_isolation(env, monkeypatch):
    api = env['api']
    item = easyorders.normalize(sample()).model_dump()
    body = {'brand_id': env['brand'], 'currency': 'EGP', 'products': [item]}
    r = await api.post('/api/assist/easyorders/apply', json=body)
    assert r.json() == {'added': 1, 'updated': 0, 'skipped': 0}
    assert (await api.post('/api/assist/easyorders/apply', json=body)).json()['skipped'] == 1
    local_id = easyorders.product_id(env['brand'], item['external_id'])
    async with SessionLocal() as db:
        p = await db.get(Product, local_id)
        p.cost = 90; p.usp = 'تفصيلة محلية'; p.url = 'https://store.example/product'
        await db.commit()
    changed = deepcopy(body); changed['products'][0]['sale_price'] = 180; changed['update_existing'] = True
    assert (await api.post('/api/assist/easyorders/apply', json=changed)).json()['updated'] == 1
    brain = (await api.get(f"/api/brands/{env['brand']}")).json()
    p = brain['products'][0]
    assert p['price'] == 180 and p['cost'] == 90 and p['usp'] == 'تفصيلة محلية'
    assert p['url'] == 'https://store.example/product'
    assert p['source']['images'] == item['images'] and p['source']['variants'] == item['variants']
    monkeypatch.setattr(easyorders, 'fetch_page', AsyncMock(return_value=([easyorders.normalize(sample())], False, 1, 0)))
    r = await api.post('/api/assist/easyorders/preview', json={'brand_id': env['brand'], 'api_key': 'test-secret-only'})
    assert r.json()['products'][0]['exists']
    other = dict(body, brand_id=env['other_brand'])
    assert (await api.post('/api/assist/easyorders/apply', json=other)).json()['added'] == 1
    assert (await api.delete(f"/api/brands/{env['brand']}/products/{local_id}")).status_code == 204
    async with SessionLocal() as db:
        assert await db.get(ProductSource, local_id) is None
        assert await db.get(Product, easyorders.product_id(env['other_brand'], item['external_id'])) is not None


@pytest.mark.parametrize('price,sale,expected', [(250, 0, 250), (250, 300, 250), (250, 180, 180), (0, 0, 0), (None, None, None)])
def test_price_semantics(price, sale, expected):
    p = easyorders.normalize(dict(sample(), price=price, sale_price=sale))
    assert p.selling_price == expected
