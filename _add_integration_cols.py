"""One-off migration: add integration_urls JSONB column to queues and campaigns."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings

cfg = get_settings()

async def run():
    engine = create_async_engine(cfg.database_url, echo=False)
    async with engine.begin() as conn:
        for table in ('chat_queues', 'chat_campaigns'):
            result = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                f"WHERE table_name='{table}' AND column_name='integration_urls'"
            ))
            if result.fetchone():
                print(f"{table}.integration_urls already exists — skipping")
            else:
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN integration_urls JSONB DEFAULT '{{}}'"
                ))
                print(f"Added integration_urls to {table}")
    await engine.dispose()

asyncio.run(run())
