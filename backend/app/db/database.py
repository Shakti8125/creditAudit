from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


engine = create_async_engine(
    settings.database.url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    echo=False,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency for getting async db sessions."""
    async with async_session_maker() as session:
        yield session
