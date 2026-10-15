"""将已保存的网页证据补成待审核记录；不调用外部 API，不写正式商品。"""
import asyncio
from app.db.mysql import database
from app.ingestion.updates import sync_history


async def main():
    try:
        print(await sync_history())
    finally:
        if database.engine:
            await database.engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
