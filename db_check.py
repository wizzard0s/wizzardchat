import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    url = 'postgresql+asyncpg://wizzardfrw:wizzardfrw@localhost:5432/wizzardfrw'
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        await conn.execute(text('SET search_path TO chat, public'))
        # campaigns columns
        r = await conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='chat_campaigns' ORDER BY ordinal_position"
        ))
        cols = [row[0] for row in r.fetchall()]
        print('chat_campaigns columns:', cols)
        # interactions
        r2 = await conn.execute(text(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name='chat_interactions'"
        ))
        print('chat_interactions exists:', r2.scalar() > 0)
        # campaigns count
        r3 = await conn.execute(text("SELECT count(*) FROM chat_campaigns"))
        print('campaigns count:', r3.scalar())

asyncio.run(main())
