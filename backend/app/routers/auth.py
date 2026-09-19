"""Login, logout, and owner-only user management."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from ..config import settings
from ..deps import DbDep, UserDep, require_owner
from ..models import Membership, User
from ..security import COOKIE_NAME, create_session, destroy_session, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    locale: str


class UserIn(BaseModel):
    email: EmailStr
    name: str = ""
    password: str = Field(min_length=8)
    role: str = "member"


class UserPatch(BaseModel):
    name: str | None = None
    password: str | None = Field(default=None, min_length=8)
    role: str | None = None
    is_active: bool | None = None
    locale: str | None = None


def _out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, role=user.role,
                   is_active=user.is_active, locale=user.locale)


@router.post("/login", response_model=UserOut)
async def login(payload: LoginIn, response: Response, db: DbDep):
    user = await db.scalar(select(User).where(User.email == payload.email.lower().strip()))
    # Always run the hash comparison shape so a missing account and a wrong
    # password take the same path.
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "الإيميل أو الباسورد غلط")

    session = await create_session(db, user)
    response.set_cookie(
        COOKIE_NAME, session.token,
        max_age=settings.session_days * 86400,
        httponly=True, samesite="lax", secure=not settings.is_sqlite, path="/",
    )
    return _out(user)


@router.post("/logout")
async def logout(request: Request, response: Response, db: DbDep):
    """Drops the server-side session too, so the token cannot be replayed."""
    if token := request.cookies.get(COOKIE_NAME):
        await destroy_session(db, token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(user: UserDep):
    return _out(user)


@router.patch("/me", response_model=UserOut)
async def update_me(payload: UserPatch, db: DbDep, user: UserDep):
    if payload.name is not None:
        user.name = payload.name
    if payload.locale is not None:
        user.locale = payload.locale
    if payload.password:
        user.password_hash = hash_password(payload.password)
    await db.commit()
    return _out(user)


# --- Owner-only user management -------------------------------------------
@router.get("/users", response_model=list[UserOut])
async def list_users(db: DbDep, user: UserDep):
    await require_owner(user)
    rows = await db.scalars(select(User).order_by(User.created_at))
    return [_out(u) for u in rows]


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(payload: UserIn, db: DbDep, user: UserDep):
    await require_owner(user)
    email = payload.email.lower().strip()
    if await db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "الإيميل ده مستخدم بالفعل")
    created = User(email=email, name=payload.name, role=payload.role,
                   password_hash=hash_password(payload.password))
    db.add(created)
    await db.commit()
    return _out(created)


@router.patch("/users/{user_id}", response_model=UserOut)
async def patch_user(user_id: str, payload: UserPatch, db: DbDep, user: UserDep):
    await require_owner(user)
    target = await db.get(User, user_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "المستخدم غير موجود")
    if target.id == user.id and payload.is_active is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مينفعش توقف حسابك بنفسك")

    if payload.name is not None:
        target.name = payload.name
    if payload.role is not None:
        target.role = payload.role
    if payload.is_active is not None:
        target.is_active = payload.is_active
    if payload.password:
        target.password_hash = hash_password(payload.password)
    await db.commit()
    return _out(target)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(user_id: str, db: DbDep, user: UserDep):
    await require_owner(user)
    if user_id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "مينفعش تمسح حسابك بنفسك")
    target = await db.get(User, user_id)
    if target is not None:
        await db.delete(target)
        await db.commit()


class MembershipIn(BaseModel):
    user_id: str
    client_id: str
    role: str = "editor"


@router.post("/memberships", status_code=201)
async def grant_membership(payload: MembershipIn, db: DbDep, user: UserDep):
    """Give a user access to one client's brands."""
    await require_owner(user)
    existing = await db.scalar(select(Membership).where(
        Membership.user_id == payload.user_id, Membership.client_id == payload.client_id))
    if existing:
        existing.role = payload.role
    else:
        db.add(Membership(**payload.model_dump()))
    await db.commit()
    return {"ok": True}


@router.delete("/memberships", status_code=204)
async def revoke_membership(user_id: str, client_id: str, db: DbDep, user: UserDep):
    await require_owner(user)
    row = await db.scalar(select(Membership).where(
        Membership.user_id == user_id, Membership.client_id == client_id))
    if row is not None:
        await db.delete(row)
        await db.commit()


@router.get("/memberships/{user_id}")
async def user_memberships(user_id: str, db: DbDep, user: UserDep):
    await require_owner(user)
    rows = await db.scalars(select(Membership).where(Membership.user_id == user_id))
    return [{"client_id": m.client_id, "role": m.role} for m in rows]
