import asyncio, asyncpg

async def main():
    conn = await asyncpg.connect("postgresql://postgres:postgres@localhost:5432/wizzardfrw")
    FLOW_ID = "f0876777-c2d2-4ecf-bd11-041a82d88afd"
    rows = await conn.fetch(
        "SELECT id, node_type, config FROM flow_nodes WHERE flow_id = $1",
        FLOW_ID
    )
    for r in rows:
        print(r["node_type"], str(r["id"]), r["config"])
    await conn.close()

asyncio.run(main())
