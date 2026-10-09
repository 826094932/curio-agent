import argparse
import asyncio
import json
from pathlib import Path
from app.ingestion.service import import_records
from app.products.schemas import ProductInput, PriceInput, ReviewInput
from app.db.mysql import database


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=['products', 'prices', 'reviews'])
    parser.add_argument('file', type=Path)
    args = parser.parse_args()
    schema = {'products': ProductInput, 'prices': PriceInput, 'reviews': ReviewInput}[args.kind]
    rows = [schema.model_validate(item) for item in json.loads(args.file.read_text(encoding='utf-8'))]
    try:
        print(json.dumps(await import_records(args.kind, rows), ensure_ascii=False, indent=2))
    finally:
        if database.engine:
            await database.engine.dispose()


if __name__ == '__main__':
    asyncio.run(main())
