"""Documented fal queue protocol. No browser keys, arbitrary models or paid retries."""
from urllib.parse import urlparse

import httpx

IMAGE_MODEL = 'fal-ai/nano-banana-pro'
IMAGE_EDIT_MODEL = IMAGE_MODEL + '/edit'
VIDEO_MODEL = 'fal-ai/kling-video/v2.6/pro/text-to-video'
VIDEO_IMAGE_MODEL = 'fal-ai/kling-video/v2.6/pro/image-to-video'
AUDIO_MODEL = 'fal-ai/elevenlabs/tts/eleven-v3'


def queue_url(value: str) -> str:
    p = urlparse(value)
    if p.scheme != 'https' or p.netloc != 'queue.fal.run' or not p.path.startswith('/fal-ai/'):
        raise ValueError('Invalid provider queue URL')
    return value


class ProviderError(Exception):
    pass


class FalProvider:
    def __init__(self, key: str):
        self.key = key

    async def request(self, method, url, body=None):
        async with httpx.AsyncClient(timeout=60, follow_redirects=False) as client:
            response = await client.request(method, queue_url(url), json=body,
                                            headers={'Authorization': f'Key {self.key}'})
        if response.status_code in (401, 403):
            raise ProviderError('مفتاح fal غير صالح أو لا يملك صلاحية التشغيل.')
        if response.status_code == 402:
            raise ProviderError('رصيد fal غير كافٍ. اشحن الحساب ثم ابدأ طلبًا جديدًا.')
        if response.is_error:
            # Do not reflect signed URLs, provider payloads or secrets to clients.
            raise ProviderError(f'رفض مزود الإنتاج الطلب (HTTP {response.status_code}). راجع إعدادات الطلب وحساب fal.')
        return response.json()

    async def submit(self, model: str, payload: dict):
        result = await self.request('POST', f'https://queue.fal.run/{model}', payload)
        for field in ('status_url', 'response_url', 'cancel_url'):
            queue_url(result[field])
        return {k: result[k] for k in ('request_id', 'status_url', 'response_url', 'cancel_url')}

    async def status(self, step):
        return await self.request('GET', step['status_url'])

    async def result(self, step):
        return await self.request('GET', step['response_url'])

    async def cancel(self, step):
        return await self.request('PUT', step['cancel_url'])

    async def check(self):
        # Read-only authenticated queue lookup; never submits a generation.
        url = f'https://queue.fal.run/{IMAGE_MODEL}/requests/00000000-0000-0000-0000-000000000000/status'
        async with httpx.AsyncClient(timeout=15, follow_redirects=False) as client:
            r = await client.get(url, headers={'Authorization': f'Key {self.key}'})
        if r.status_code in (401, 403):
            raise ProviderError('المفتاح غير صالح أو صلاحياته غير كافية.')
        if r.status_code not in (200, 404, 422):
            raise ProviderError('تعذّر التحقق من الاتصال الآن.')
        return {'reachable': True, 'message': 'استجاب API لفحص القراءة. صلاحية الموديل والرصيد تتأكد عند أول إنتاج.'}
