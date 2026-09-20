"""Direct OpenAI Images and Higgsfield v2 APIs; no implicit paid retries."""
import base64
import ipaddress
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import aiohttp
import httpx

from .fal_provider import ProviderError
from .public_fetch import PublicResolver

IMAGE_MODELS = {
    'sunburst': {'provider': 'openai', 'model': 'gpt-image-2.5-sunburst', 'label': 'GPT Image 2.5 Sunburst'},
    'flare': {'provider': 'openai', 'model': 'gpt-image-2.5-flare', 'label': 'GPT Image 2.5 Flare'},
    'nano_banana': {'provider': 'fal', 'model': 'fal-ai/nano-banana-pro', 'label': 'Nano Banana Pro'},
}
UGC_MODEL = 'bytedance/seedance-2.5/reference-to-video'
DEFAULTS = {'image_model': 'nano_banana', 'ugc_model': 'seedance_2_5',
            'video_model': 'kling_2_6', 'audio_model': 'eleven_v3'}
UGC_FORMATS = {
    'review': 'Creator demonstrates the product and explains its supplied benefits naturally to camera.',
    'unboxing': 'Creator opens the package, reveals the exact product, then shows its key details.',
    'tutorial': 'Creator demonstrates realistic, ordered steps for using the product.',
    'try_on': 'Creator wears the referenced item and shows its fit and material naturally.',
}


def public_https(url):
    """Credentials never accompany storage calls; resolve and pin public IPs."""
    p = urlparse(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('رابط ملف المزود غير صالح.')
    try:
        ip = ipaddress.ip_address(p.hostname)
    except ValueError:
        ip = None
    if ip and (not ip.is_global or ip.is_multicast or ip.is_reserved):
        raise ValueError('رابط ملف المزود غير آمن.')
    return url


def public_session():
    return aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver(), use_dns_cache=False),
                                 trust_env=False, timeout=aiohttp.ClientTimeout(total=180))


def check_response(response, provider):
    if response.is_error:
        code = response.status_code
        message = {401: 'المفتاح غير صالح.', 403: 'الحساب لا يملك صلاحية الموديل.',
                   402: 'الرصيد غير كافٍ.', 429: 'حد الاستخدام أو الرصيد لا يسمح بالطلب الآن.'}.get(
                       code, 'راجع إعدادات الطلب وحساب المزود.')
        raise ProviderError(f'{provider}: {message} (HTTP {code})')


class OpenAIProvider:
    def __init__(self, key):
        self.key = key

    async def request(self, endpoint, **kwargs):
        # Image/transcription calls are synchronous and non-idempotent. Never auto-retry.
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=20), follow_redirects=False) as client:
            response = await client.post('https://api.openai.com/v1/' + endpoint,
                                        headers={'Authorization': f'Bearer {self.key}'}, **kwargs)
        check_response(response, 'OpenAI')
        return response.json(), response.headers.get('x-request-id', '')

    async def image(self, model, payload, references):
        if model not in {m['model'] for m in IMAGE_MODELS.values() if m['provider'] == 'openai'}:
            raise ValueError('موديل الصور غير مدعوم.')
        body = dict(payload, model=model, n=1, output_format='png')
        if references:
            files = [('image[]', (f'reference-{i}.png', raw, 'image/png')) for i, raw in enumerate(references)]
            result, request_id = await self.request('images/edits', data={k: str(v) for k, v in body.items()}, files=files)
        else:
            result, request_id = await self.request('images/generations', json=body)
        try:
            raw = base64.b64decode(result['data'][0]['b64_json'], validate=True)
        except (KeyError, IndexError, ValueError, TypeError):
            raise ProviderError('OpenAI لم يرجع صورة صالحة. راجع سجل المزود قبل إعادة الإنتاج.') from None
        return raw, request_id

    async def transcribe(self, path, language):
        raw = Path(path).read_bytes()
        if len(raw) > 24 * 1024 * 1024:
            raise ValueError('الصوت أكبر من حد التفريغ.')
        return await self.request('audio/transcriptions', files={'file': ('speech.mp3', raw, 'audio/mpeg')},
                                  data={'model': 'whisper-1', 'response_format': 'verbose_json',
                                        'timestamp_granularities[]': 'word', 'language': language})

    async def check(self):
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            r = await client.get('https://api.openai.com/v1/models/gpt-image-2.5-sunburst',
                                 headers={'Authorization': f'Bearer {self.key}'})
        check_response(r, 'OpenAI')
        return {'reachable': True, 'message': 'تم التحقق من الوصول إلى موديل Sunburst. الرصيد وإتاحة التوليد يتأكدان عند الإنتاج.'}


class HiggsfieldProvider:
    def __init__(self, key):
        self.key = key

    async def request(self, method, path, body=None):
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, 'https://api.higgsfield.ai/' + path,
                                            headers={'Authorization': f'Key {self.key}'}, json=body)
        check_response(response, 'Higgsfield')
        return response.json() if response.content else {}

    async def upload(self, raw):
        signed = await self.request('POST', 'files/generate-upload-url', {'content_type': 'image/png'})
        upload_url = public_https(signed['upload_url'])
        public_url = public_https(signed['public_url'])
        headers = signed.get('upload_headers', {'Content-Type': 'image/png'})
        if any(k.lower() in ('authorization', 'cookie', 'host') for k in headers):
            raise ProviderError('Higgsfield أعاد إعداد رفع غير صالح.')
        async with public_session() as session:
            async with session.put(upload_url, data=raw, headers=headers, allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise ProviderError('تعذّر رفع الصورة المرجعية إلى Higgsfield.')
        return public_url

    async def submit(self, model, payload):
        if model != UGC_MODEL:
            raise ValueError('موديل الفيديو غير مدعوم.')
        result = await self.request('POST', model, payload)
        # Construct status paths ourselves, never follow credential-bearing provider URLs.
        request_id = str(UUID(result['request_id']))
        return {'request_id': request_id}

    async def status(self, step):
        result = await self.request('GET', f"requests/{UUID(step['request_id'])}/status")
        state = result.get('status')
        if state in ('failed', 'nsfw', 'canceled'):
            raise ProviderError(f'Higgsfield: انتهى الطلب بدون فيديو ({state}). راجع الطلب في حساب المزود.')
        if state not in ('queued', 'in_progress', 'completed'):
            raise ProviderError('Higgsfield أعاد حالة غير معروفة. راجع الطلب في حساب المزود.')
        return dict(result, status='COMPLETED' if state == 'completed' else 'IN_PROGRESS')

    async def cancel(self, step):
        return await self.request('POST', f"requests/{UUID(step['request_id'])}/cancel")

    async def check(self):
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            r = await client.get('https://api.higgsfield.ai/requests/00000000-0000-0000-0000-000000000000/status',
                                 headers={'Authorization': f'Key {self.key}'})
        if r.status_code not in (200, 404):
            check_response(r, 'Higgsfield')
            raise ProviderError('تعذّر فحص Higgsfield الآن.')
        return {'reachable': True, 'message': 'استجاب API لفحص القراءة. إتاحة الموديل والرصيد تتأكد عند أول إنتاج.'}
