import asyncio
from app.ingestion.service import rebuild
from app.db.mysql import database


async def main():
    try:
        print(await rebuild())
    finally:
        if database.engine:
            await database.engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
