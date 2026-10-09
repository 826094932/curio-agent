import asyncio
import hashlib
import json
from datetime import timezone
from sqlalchemy import select
from app.db.models import Product, Price, Review, ImportJob
from app.db.mysql import database
from app.db.chroma import vectors
from app.products.schemas import utc
from app.errors import AppError

index_lock = asyncio.Lock()


def content_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def product_document(row):
    return f'{row.brand} {row.name}\n{row.summary}\n' + json.dumps(row.specs, ensure_ascii=False, sort_keys=True)


async def index_product(row):
    if row.status != 'active':
        await asyncio.to_thread(vectors.collection('product_knowledge').delete, ids=[row.id])
        return
    text = product_document(row)
    metadata = {'product_id': row.id, 'category': row.category_code, 'brand': row.brand, 'source_url': row.source_url, 'content_hash': content_hash([text, row.source_url]), 'updated_ts': int(row.source_updated_at.replace(tzinfo=timezone.utc).timestamp())}
    await asyncio.to_thread(vectors.upsert, 'product_knowledge', row.id, text, metadata)


async def index_review(row):
    metadata = {'product_id': row.product_id, 'aspect': row.aspect, 'sentiment': row.sentiment, 'source_url': row.source_url, 'content_hash': row.content_hash}
    await asyncio.to_thread(vectors.upsert, 'review_knowledge', row.id, row.content, metadata)


async def import_records(kind, records):
    job = ImportJob(job_type=kind, total_count=len(records))
    async with database.session() as db:
        db.add(job)
        await db.commit()
    completed = 0
    errors = []
    async with index_lock:
        for index, data in enumerate(records):
            try:
                values = data.model_dump()
                for key, value in values.items():
                    if key.endswith('_url'):
                        values[key] = str(value)
                    if key in {'source_updated_at', 'reviewed_at', 'captured_at'}:
                        values[key] = utc(value)
                async with database.session() as db:
                    if kind == 'products':
                        values['content_hash'] = content_hash(values)
                        row = await db.get(Product, values['id'])
                        if row is None:
                            row = Product(**values)
                            db.add(row)
                        else:
                            for key, value in values.items():
                                setattr(row, key, value)
                    elif kind == 'reviews':
                        if not await db.get(Product, values['product_id']):
                            raise ValueError('商品不存在')
                        values['content_hash'] = content_hash(values)
                        row = await db.get(Review, values['id'])
                        if row is None:
                            row = Review(**values)
                            db.add(row)
                        else:
                            for key, value in values.items():
                                setattr(row, key, value)
                    else:
                        if not await db.get(Product, values['product_id']):
                            raise ValueError('商品不存在')
                        row = await db.scalar(select(Price).where(Price.product_id == values['product_id'], Price.channel == values['channel'], Price.captured_at == values['captured_at']))
                        if row is None:
                            row = Price(**values)
                            db.add(row)
                        elif any(getattr(row, k) != v for k, v in values.items()):
                            raise ValueError('同一价格快照内容冲突，请提供正确的采集时间')
                    await db.commit()
                if kind == 'products':
                    await index_product(row)
                elif kind == 'reviews':
                    await index_review(row)
                completed += 1
            except Exception as exc:
                errors.append({'index': index, 'code': type(exc).__name__, 'message': '写入失败，请核对记录、商品外键或 Embedding 环境；重新导入可修复未完成索引'})
    async with database.session() as db:
        stored = await db.get(ImportJob, job.id)
        stored.success_count, stored.status = completed, ('failed' if errors else 'succeeded')
        stored.error_report = {'errors': errors}
        await db.commit()
    return {'job_id': job.id, 'status': stored.status, 'total_count': len(records), 'success_count': completed, 'errors': errors}


async def rebuild():
    # 原地幂等修复索引，不删除整个 Collection；失败时可再次执行。
    async with index_lock:
        async with database.session() as db:
            products = (await db.scalars(select(Product))).all()
            reviews = (await db.scalars(select(Review))).all()
        for row in products:
            await index_product(row)
        for row in reviews:
            await index_review(row)
    return {'products': len(products), 'reviews': len(reviews)}
