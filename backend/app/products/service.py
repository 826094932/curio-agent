import asyncio
import re
from datetime import timedelta
from sqlalchemy import select, or_
from app.config import settings
from app.db.mysql import database
from app.db.chroma import vectors
from app.db.models import Product, Price, Review, now
from app.products.scoring import matches, score
from app.errors import AppError
from app.products.matching import matches_model, local_coverage


def iso(value):
    return value.isoformat() + 'Z'


async def prices(ids, channels=None):
    async with database.session() as db:
        statement = select(Price).where(Price.product_id.in_(ids)).order_by(Price.captured_at.desc(), Price.id.desc())
        if channels:
            statement = statement.where(Price.channel.in_(channels))
        rows = (await db.scalars(statement)).all()
    seen, result = set(), []
    for row in rows:
        key = (row.product_id, row.channel)
        if key in seen:
            continue
        seen.add(key)
        result.append({'product_id': row.product_id, 'channel': row.channel, 'final_price': str(row.final_price), 'currency': row.currency, 'in_stock': row.in_stock, 'source_url': row.product_url, 'captured_at': iso(row.captured_at), 'is_stale': now() - row.captured_at > timedelta(hours=settings.price_stale_hours)})
    return result


async def details(ids):
    async with database.session() as db:
        rows = (await db.scalars(select(Product).where(Product.id.in_(ids), Product.status == 'active'))).all()
    offers = await prices(ids)
    items = []
    for row in rows:
        available = [p for p in offers if p['product_id'] == row.id and p['in_stock']]
        # 优先新鲜价格；仅剩过期价格时保留标识，不能伪装成实时报价。
        available.sort(key=lambda p: (p['is_stale'], float(p['final_price'])))
        items.append({'id': row.id, 'name': row.name, 'model': row.model, 'category': row.category_code, 'brand': row.brand, 'specs': row.specs, 'summary': row.summary, 'source_url': row.source_url, 'updated_at': iso(row.source_updated_at), 'price': available[0] if available else {}})
    return items


def eligible(item, state):
    if state.get('category') and item['category'] != state['category']:
        return False
    if state.get('requested_models') and not any(matches_model(item, name) for name in state['requested_models']):
        return False
    if item['brand'].lower() in [x.lower() for x in state.get('excluded_brands', [])]:
        return False
    if not matches(item['specs'], state.get('hard_constraints', {})):
        return False
    low, high = state.get('budget_min'), state.get('budget_max')
    price = item['price'].get('final_price')
    if low is not None or high is not None:
        if price is None:
            return False
        return (low is None or float(price) >= low) and (high is None or float(price) <= high)
    return True


async def search(data, state=None):
    state = dict(state or {})
    state['category'] = state.get('category') or data.category
    if data.min_price is not None:
        state['budget_min'] = max(state.get('budget_min') or 0, data.min_price)
    if data.max_price is not None:
        old_max = state.get('budget_max')
        state['budget_max'] = min(old_max, data.max_price) if old_max is not None else data.max_price
    constraints = dict(state.get('hard_constraints', {}))
    constraints.update(data.filters)
    # 原会话约束还会在后面独立校验，工具无法借过滤参数放宽用户硬要求。
    state['hard_constraints'] = constraints
    matches({}, constraints)
    async with database.session() as db:
        statement = select(Product.id).where(Product.status == 'active')
        if state.get('category'):
            statement = statement.where(Product.category_code == state['category'])
        if data.brands:
            statement = statement.where(Product.brand.in_(data.brands))
        candidates = (await db.scalars(statement)).all()
        exact = (await db.scalars(statement.where(or_(Product.model == data.query, Product.name == data.query)))).all()
    records = {p['id']: p for p in await details(candidates)}
    allowed = [id for id, item in records.items() if eligible(item, state)]
    if not allowed:
        constraints = state.get('hard_constraints', {})
        missing = []
        for item in records.values():
            absent = [key.removesuffix('_gte').removesuffix('_lte') for key in constraints
                      if key.removesuffix('_gte').removesuffix('_lte') not in item['specs']]
            if absent or ((state.get('budget_min') is not None or state.get('budget_max') is not None) and not item['price']):
                missing.append({'name': item['name'], 'missing_specs': absent, 'missing_price': not bool(item['price'])})
        reason = 'NO_ACTIVE_PRODUCTS_IN_CATEGORY' if not candidates else ('NO_MATCHING_MODELS' if state.get('requested_models') else 'NO_MATCHING_CONSTRAINTS')
        return {'items': [], 'sources': [], 'reason': reason,
                'active_count': len(candidates), 'data_gaps': missing[:5], **local_coverage([], state)}
    if state.get('requested_models'):
        # 对指定型号直接核对全量结构化身份，不用近邻向量代替型号，
        # 也不让某款型号排在 Top-K 之外导致误判缺失。
        ordered = []
        for name in state['requested_models']:
            for id in allowed:
                if matches_model(records[id], name) and id not in ordered:
                    ordered.append(id)
        items = [{**records[id], 'retrieval_score': None, 'evidence_id': f'product:{id}'} for id in ordered[:data.top_k]]
        coverage = local_coverage(items, state)
        return {'items': items,
                'sources': [{'id': f"product:{item['id']}", 'url': item['source_url'], 'text': item['summary']} for item in items],
                'retrieval_mode': 'model_match', 'active_count': len(candidates), **coverage,
                'reason': None if coverage['local_sufficient'] else 'PARTIAL_MODEL_COVERAGE'}
    terms = [term.lower() for term in re.findall(r'[A-Za-z][A-Za-z0-9+.-]*', data.query)]
    lexical = sorted(allowed, key=lambda id: sum(term in f"{records[id]['name']} {records[id]['model']}".lower() for term in terms), reverse=True)
    lexical = [id for id in lexical if any(term in f"{records[id]['name']} {records[id]['model']}".lower() for term in terms)]
    fallback = False
    try:
        hits = await asyncio.to_thread(vectors.query, 'product_knowledge', data.query, {'product_id': {'$in': allowed}}, max(30, data.top_k))
    except Exception as exc:
        if not exact and not lexical:
            raise AppError(503, 'VECTOR_UNAVAILABLE', '向量检索暂不可用，请检查 Embedding 模型与 Chroma') from exc
        hits = []
        fallback = True
    if not hits:
        if not exact and not lexical:
            raise AppError(503, 'VECTOR_UNAVAILABLE', '向量索引没有命中且无法通过商品名称检索，请修复索引')
        fallback = True
    ordered = [id for id in exact if id in allowed]
    if fallback:
        ordered.extend(id for id in lexical if id not in ordered)
    evidence = {}
    for hit in hits:
        id = hit['metadata']['product_id']
        if id not in ordered:
            ordered.append(id)
        evidence.setdefault(id, hit)
    items = [{**records[id], 'retrieval_score': evidence.get(id, {}).get('score'), 'evidence_id': evidence.get(id, {}).get('evidence_id')} for id in ordered[:data.top_k]]
    selected = {p['id'] for p in items}
    sources = [{'id': h['evidence_id'], 'url': h['metadata']['source_url'], 'text': h['text']} for id, h in evidence.items() if id in selected]
    if fallback:
        sources = [{'id': f'product:{id}', 'url': records[id]['source_url'], 'text': records[id]['summary']} for id in selected]
    return {'items': items, 'sources': sources, 'retrieval_mode': 'keyword_fallback' if fallback else 'vector'}


async def reviews(data):
    result = []
    for product_id in data.product_ids[:10]:
        condition = {'product_id': product_id}
        if data.aspects:
            condition = {'$and': [condition, {'aspect': {'$in': data.aspects}}]}
        hits = await asyncio.to_thread(vectors.query, 'review_knowledge', data.query, condition, data.top_k_per_product)
        async with database.session() as db:
            statement = select(Review).where(Review.product_id == product_id, Review.sentiment == 'negative')
            if data.aspects:
                statement = statement.where(Review.aspect.in_(data.aspects))
            negative = await db.scalar(statement.order_by(Review.reviewed_at.desc()).limit(1))
        for h in hits:
            result.append({'id': h['evidence_id'], 'url': h['metadata']['source_url'], 'product_id': product_id, 'text': h['text'], 'sentiment': h['metadata']['sentiment']})
        if negative and not any(x['id'] == negative.id for x in result):
            result.append({'id': negative.id, 'url': negative.source_url, 'product_id': product_id, 'text': negative.content, 'sentiment': 'negative'})
    return result[:30]


async def compare(data, state):
    items = await details(data.product_ids)
    valid = [item for item in items if item['category'] == data.category and eligible(item, state)]
    return {**score(valid, data.category, data.weights), 'excluded_ids': [id for id in data.product_ids if id not in {p['id'] for p in valid}]}
