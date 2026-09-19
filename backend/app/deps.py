"""Request dependencies: who is calling, and what they may touch.

Access always flows User -> Membership -> Client -> Brand. An owner bypasses
membership; nobody else does, which is what keeps one agency client's work
invisible to another.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import get_db
from .models import Brand, Client, Membership, User
from .security import COOKIE_NAME, resolve_session

DbDep = Annotated[AsyncSession, Depends(get_db)]

ROLE_RANK = {"viewer": 0, "editor": 1, "admin": 2}


async def current_user(
    db: DbDep,
    ecbt_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> User:
    user = await resolve_session(db, ecbt_session or "")
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "غير مسجّل الدخول")
    return user


UserDep = Annotated[User, Depends(current_user)]


async def require_owner(user: UserDep) -> User:
    if user.role != "owner":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ده إجراء للمالك بس")
    return user


async def client_role(db: AsyncSession, user: User, client_id: str) -> str | None:
    if user.role == "owner":
        return "admin"
    return await db.scalar(
        select(Membership.role).where(
            Membership.user_id == user.id, Membership.client_id == client_id
        )
    )


async def accessible_client_ids(db: AsyncSession, user: User) -> list[str] | None:
    """None means unrestricted (owner)."""
    if user.role == "owner":
        return None
    rows = await db.scalars(select(Membership.client_id).where(Membership.user_id == user.id))
    return list(rows)


async def get_client(db: AsyncSession, user: User, client_id: str, need: str = "viewer") -> Client:
    client = await db.get(Client, client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "العميل غير موجود")
    role = await client_role(db, user, client_id)
    if role is None or ROLE_RANK[role] < ROLE_RANK[need]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "مالكش صلاحية على العميل ده")
    return client


async def get_brand(db: AsyncSession, user: User, brand_id: str, need: str = "viewer") -> Brand:
    """Load a brand with its whole Brain, after checking access."""
    brand = await db.scalar(
        select(Brand)
        .where(Brand.id == brand_id)
        .options(
            selectinload(Brand.products),
            selectinload(Brand.avatars),
            selectinload(Brand.competitors),
            selectinload(Brand.voc_entries),
        )
    )
    if brand is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "البراند غير موجود")
    role = await client_role(db, user, brand.client_id)
    if role is None or ROLE_RANK[role] < ROLE_RANK[need]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "مالكش صلاحية على البراند ده")
    return brand
