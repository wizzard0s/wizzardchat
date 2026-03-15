"""Add integration_urls to the correct chat schema tables."""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings

cfg = get_settings()

async def run():
    engine = create_async_engine(cfg.database_url)
    async with engine.begin() as conn:
        for full_table in ('chat.chat_queues', 'chat.chat_campaigns'):
            schema, tbl = full_table.split('.')
            result = await conn.execute(text(
                "SELECT 1 FROM information_schema.columns "
                f"WHERE table_schema='{schema}' AND table_name='{tbl}' "
                "AND column_name='integration_urls'"
            ))
            if result.fetchone():
                print(f"{full_table}.integration_urls already exists — skipping")
            else:
                await conn.execute(text(
                    f"ALTER TABLE {full_table} ADD COLUMN integration_urls JSONB DEFAULT '{{}}'"
                ))
                print(f"Added integration_urls to {full_table}")
    await engine.dispose()

asyncio.run(run())
