import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.config import get_settings
cfg = get_settings()
async def run():
    engine = create_async_engine(cfg.database_url)
    async with engine.connect() as c:
        r = await c.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name IN ('chat_queues','chat_campaigns') "
            "AND column_name='integration_urls'"
        ))
        rows = r.fetchall()
        print("Found:", rows)
        if not rows:
            for tbl in ('chat_queues', 'chat_campaigns'):
                await c.execute(text(
                    f"ALTER TABLE {tbl} ADD COLUMN integration_urls JSONB DEFAULT '{{}}'"
                ))
                print(f"Added integration_urls to {tbl}")
            await c.commit()
        else:
            print("Already present in both tables")
    await engine.dispose()
asyncio.run(run())
