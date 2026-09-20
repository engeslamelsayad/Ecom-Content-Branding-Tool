"""Server-only credentials, encrypted independently from the database."""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import settings
from .models import Integration


def cipher() -> Fernet:
    if settings.connection_encryption_key:
        return Fernet(settings.connection_encryption_key.encode())
    # Railway /data volume persists this across deploys. Back it up with the DB.
    path = Path(settings.storage_dir) / '.integration.key'
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'wb') as f:
            f.write(Fernet.generate_key())
    return Fernet(path.read_bytes())


async def fal_key(db) -> str:
    return await provider_key(db, 'fal')


async def provider_key(db, provider: str) -> str:
    env = {'fal': settings.fal_key, 'openai': settings.openai_api_key,
           'higgsfield': settings.higgsfield_key}
    if provider not in env:
        raise ValueError('مزود غير مدعوم.')
    row = await db.get(Integration, provider)
    if row and row.encrypted_key:
        try:
            return cipher().decrypt(row.encrypted_key.encode()).decode()
        except InvalidToken:
            raise ValueError('تعذّر فك مفتاح الاتصال. أعد إدخاله من إعدادات الإنتاج.') from None
    return env[provider].strip()
