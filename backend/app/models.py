"""ORM models.

Shape of the domain: a Client (an agency customer, or your own company) owns
Brands. A Brand owns its Brand Brain -- the persistent context every module
reads from and writes back to -- plus products, avatars, competitors, VoC
entries, generated runs and uploaded assets.

Users reach a Brand only through a Membership on its Client, which is what
gives the per-client isolation.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# --------------------------------------------------------------------------
# Identity & access
# --------------------------------------------------------------------------
class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(Text)
    # "owner" can manage users and every client; everyone else is scoped by Membership.
    role: Mapped[str] = mapped_column(String(20), default="member")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    locale: Mapped[str] = mapped_column(String(10), default="ar")

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Client(Base, TimestampMixin):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200))
    notes: Mapped[str] = mapped_column(Text, default="")

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )
    brands: Mapped[list[Brand]] = relationship(
        back_populates="client", cascade="all, delete-orphan"
    )


class Membership(Base, TimestampMixin):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_member_user_client"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    # admin = manage the client and its brands; editor = run modules; viewer = read only.
    role: Mapped[str] = mapped_column(String(20), default="editor")

    user: Mapped[User] = relationship(back_populates="memberships")
    client: Mapped[Client] = relationship(back_populates="memberships")


class Session(Base):
    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------
# Brand Brain
# --------------------------------------------------------------------------
class Brand(Base, TimestampMixin):
    __tablename__ = "brands"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    client_id: Mapped[str] = mapped_column(ForeignKey("clients.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    one_liner: Mapped[str] = mapped_column(Text, default="")
    industry: Mapped[str] = mapped_column(String(120), default="")
    market: Mapped[str] = mapped_column(String(60), default="EG")
    dialect: Mapped[str] = mapped_column(String(40), default="egyptian")
    stage: Mapped[str] = mapped_column(String(40), default="launch")

    # The living strategy record. Keys mirror the skills' own vocabulary:
    # discovery, heart, verbal, positioning, visual, touchpoints, architecture,
    # onboarding, awareness, mechanism.
    core: Mapped[dict] = mapped_column(JSON, default=dict)

    client: Mapped[Client] = relationship(back_populates="brands")
    products: Mapped[list[Product]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    avatars: Mapped[list[Avatar]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    competitors: Mapped[list[Competitor]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )
    voc_entries: Mapped[list[VoCEntry]] = relationship(
        back_populates="brand", cascade="all, delete-orphan"
    )


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    usp: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(Text, default="")
    currency: Mapped[str] = mapped_column(String(8), default="EGP")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    brand: Mapped[Brand] = relationship(back_populates="products")


class Avatar(Base, TimestampMixin):
    __tablename__ = "avatars"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    brand: Mapped[Brand] = relationship(back_populates="avatars")


class Competitor(Base, TimestampMixin):
    __tablename__ = "competitors"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="direct")
    data: Mapped[dict] = mapped_column(JSON, default=dict)

    brand: Mapped[Brand] = relationship(back_populates="competitors")


class VoCEntry(Base, TimestampMixin):
    """Real customer language. Feeding this beats the skill's simulated VoC."""

    __tablename__ = "voc_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(60), default="review")
    category: Mapped[str] = mapped_column(String(20), default="motivation")  # MECLabs M / V / A
    text: Mapped[str] = mapped_column(Text)

    brand: Mapped[Brand] = relationship(back_populates="voc_entries")


# --------------------------------------------------------------------------
# Work products
# --------------------------------------------------------------------------
class Run(Base, TimestampMixin):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    module_key: Mapped[str] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(300), default="")
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|error
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    output_md: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")

    model: Mapped[str] = mapped_column(String(60), default="")
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # Review runs park their structured scorecard here.
    scores: Mapped[dict] = mapped_column(JSON, default=dict)
    # Parent run for a single regenerated section of a multi-part plan.
    parent_run_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    section_key: Mapped[str] = mapped_column(String(80), default="")


class Asset(Base, TimestampMixin):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    brand_id: Mapped[str] = mapped_column(ForeignKey("brands.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # image | video | frame | screenshot
    filename: Mapped[str] = mapped_column(String(300))
    path: Mapped[str] = mapped_column(Text)
    media_type: Mapped[str] = mapped_column(String(80), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
