"""Fix: add integration_urls column to chat schema tables."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings

cfg = get_settings()
SCHEMA = cfg.db_schema  # 'chat'

async def run():
    engine = create_async_engine(cfg.database_url)
    async with engine.begin() as conn:
        for table in ('queues', 'campaigns'):
            full = f"{SCHEMA}.{table}"
            result = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                f"WHERE table_schema='{SCHEMA}' AND table_name='{table}' "
                "AND column_name='integration_urls'"
            ))
            if result.fetchone():
                print(f"{full}.integration_urls already exists")
            else:
                await conn.execute(text(
                    f"ALTER TABLE {full} ADD COLUMN integration_urls JSONB DEFAULT '{{}}'"
                ))
                print(f"Added integration_urls to {full}")
    await engine.dispose()

asyncio.run(run())
