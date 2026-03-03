import asyncio, sys
sys.path.insert(0, '.')
from app.database import engine
from sqlalchemy import text

async def test():
    try:
        async with engine.begin() as conn:
            r = await conn.execute(text('SELECT version()'))
            print('DB OK:', r.fetchone()[0][:50])
            r2 = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='queues' ORDER BY ordinal_position"
            ))
            print('queues columns:', [row[0] for row in r2.fetchall()])
            r3 = await conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='campaigns' ORDER BY ordinal_position"
            ))
            print('campaigns columns:', [row[0] for row in r3.fetchall()])
    except Exception as e:
        print('DB ERROR:', type(e).__name__, e)
    finally:
        await engine.dispose()

asyncio.run(test())
