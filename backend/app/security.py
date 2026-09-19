"""Password hashing and server-side sessions."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .models import Session, User

_hasher = PasswordHasher()
COOKIE_NAME = "ecbt_session"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


async def create_session(db: AsyncSession, user: User) -> Session:
    session = Session(
        token=secrets.token_urlsafe(32),
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.session_days),
    )
    db.add(session)
    await db.commit()
    return session


async def resolve_session(db: AsyncSession, token: str) -> User | None:
    if not token:
        return None
    row = await db.get(Session, token)
    if row is None:
        return None

    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite hands back naive datetimes
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        await db.delete(row)
        await db.commit()
        return None

    user = await db.get(User, row.user_id)
    return user if user and user.is_active else None


async def destroy_session(db: AsyncSession, token: str) -> None:
    await db.execute(delete(Session).where(Session.token == token))
    await db.commit()


async def ensure_seed_owner(db: AsyncSession) -> None:
    """Create the first owner account from env vars, once."""
    existing = await db.scalar(select(User).limit(1))
    if existing is not None:
        return
    db.add(User(
        email=settings.admin_email.lower().strip(),
        name=settings.admin_name,
        password_hash=hash_password(settings.admin_password),
        role="owner",
    ))
    await db.commit()
