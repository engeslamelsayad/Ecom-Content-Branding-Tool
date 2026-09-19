"""Async SQLAlchemy engine, session factory and schema bootstrap."""
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
    # SQLite's async driver does not take pool sizing arguments.
    **({} if settings.is_sqlite else {"pool_size": 5, "max_overflow": 10}),
)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from . import models  # noqa: F401  (registers mappers before create_all)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
