"""Async SQLAlchemy engine & session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=5,
    max_overflow=5,
    pool_timeout=10,
    pool_pre_ping=True,   # drop dead connections before using them
    # asyncpg server_settings persists for the full connection lifetime, including
    # pooled connections — more reliable than the sync event-listener approach.
    connect_args={"server_settings": {"search_path": f"{settings.db_schema},public"}},
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
