"""Check actual table names and schema."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings

cfg = get_settings()

async def run():
    engine = create_async_engine(cfg.database_url)
    async with engine.connect() as conn:
        # List tables in ALL schemas
        r = await conn.execute(text(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type='BASE TABLE' "
            "AND table_name LIKE '%queue%' OR table_name LIKE '%campaign%' "
            "ORDER BY table_schema, table_name"
        ))
        for row in r.fetchall():
            print(row)
    await engine.dispose()

asyncio.run(run())
