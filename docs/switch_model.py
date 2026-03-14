import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

async def go():
    engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432/wizzardfrw")
    async with AsyncSession(engine) as db:
        r = await db.execute(text(
            "UPDATE flow_nodes "
            "SET config = jsonb_set(config, '{model}', '\"wizzardai://ollama/llama3.2:1b\"') "
            "WHERE id = '1471e4ee-de47-4c6b-8697-f0d333bc1e1e' "
            "RETURNING id, config->>'model' as model"
        ))
        row = r.fetchone()
        await db.commit()
        print("Updated node model to:", row[1] if row else "NOT FOUND")
    await engine.dispose()

asyncio.run(go())
