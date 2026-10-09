import asyncio
import json
from time import perf_counter
from langchain_core.tools import StructuredTool
from sqlalchemy import select
from app.db.mysql import database
from app.db.models import Preference, ToolLog
from app.products.schemas import SearchInput, IdsInput, ReviewSearch, CompareInput, PreferenceRead, PreferenceWrite
from app.products import service
from app.errors import AppError


def build_tools(user_id, run_id, state, evidence, ranked, allow_save, emit):
    """每轮创建工具闭包，用户身份来自后端认证，模型无法指定 user_id。"""
    counts = {}
    total = 0

    async def search_products(**values):
        result = await service.search(SearchInput(**values), state)
        result['items'] = [p for p in result['items'] if service.eligible(p, state)]
        state['candidate_product_ids'] = [p['id'] for p in result['items']]
        evidence.extend(result['sources'])
        return result

    async def get_product_details(**values):
        items = await service.details(values['product_ids'])
        return {'items': items, 'missing_product_ids': [id for id in values['product_ids'] if id not in {p['id'] for p in items}]}

    async def get_current_prices(**values):
        return {'items': await service.prices(values['product_ids'])}

    async def search_reviews(**values):
        result = await service.reviews(ReviewSearch(**values))
        evidence.extend(result)
        return {'items': result}

    async def compare_products(**values):
        result = await service.compare(CompareInput(**values), state)
        ranked[:] = result['items'][:3]
        state['last_recommended_product_ids'] = [p['id'] for p in ranked]
        return result

    async def get_user_preference(**values):
        async with database.session() as db:
            rows = (await db.scalars(select(Preference).where(Preference.user_id == user_id, Preference.category.in_(['general', values.get('category') or 'general'])))).all()
        return {'items': [row.preferences for row in rows]}

    async def save_user_preference(**values):
        if not values['consent'] or not allow_save:
            raise AppError(403, 'CONSENT_REQUIRED', '需要本轮用户勾选保存偏好授权')
        category = values.get('category') or 'general'
        async with database.session() as db:
            row = await db.scalar(select(Preference).where(Preference.user_id == user_id, Preference.category == category))
            if row is None:
                row = Preference(user_id=user_id, category=category)
                db.add(row)
            row.preferences = values['preferences']
            await db.commit()
        return {'saved': True}

    definitions = [
        (search_products, SearchInput, '按自然语言、预算、品类和硬约束检索商品。filters 使用规格字段，例如 storage_gb_gte: 256 表示至少 256GB。'),
        (get_product_details, IdsInput, '读取商品的可信规格、型号、来源。'),
        (get_current_prices, IdsInput, '读取最新价格快照、渠道、采集时间和是否过期。'),
        (search_reviews, ReviewSearch, '检索评价证据，保留负面反馈。'),
        (compare_products, CompareInput, '确定性比较评分。权重键必须为规格字段，例如 battery_mah、weight_g；不传权重使用品类默认规则。'),
        (get_user_preference, PreferenceRead, '获取当前用户已授权保存的偏好。'),
        (save_user_preference, PreferenceWrite, '仅在用户明确授权时保存当前用户偏好。'),
    ]

    def audited(fn):
        async def call(**kwargs):
            nonlocal total
            name = fn.__name__
            signature = name + json.dumps(kwargs, sort_keys=True, ensure_ascii=False)
            counts[signature] = counts.get(signature, 0) + 1
            total += 1
            if counts[signature] > 2 or total > 20:
                return {'ok': False, 'error': 'TOOL_CALL_LIMIT'}
            await emit('status', {'stage': name})
            start = perf_counter()
            try:
                result = await asyncio.wait_for(fn(**kwargs), timeout=45)
                response = {'ok': True, 'data': result}
            except (AppError, ValueError) as exc:
                response = {'ok': False, 'error': getattr(exc, 'code', 'INVALID_ARGUMENT'), 'message': getattr(exc, 'message', str(exc))}
            except Exception:
                response = {'ok': False, 'error': 'TOOL_UNAVAILABLE', 'message': '工具暂不可用，不能据此编造结果'}
            async with database.session() as db:
                db.add(ToolLog(run_id=run_id, tool_name=name,
                               arguments_redacted={'fields': list(kwargs), 'product_ids': kwargs.get('product_ids', [])},
                               result_summary={'ok': response['ok'], 'error': response.get('error'), 'count': len(response.get('data', {}).get('items', []))},
                               status='succeeded' if response['ok'] else 'failed', latency_ms=int((perf_counter() - start) * 1000)))
                await db.commit()
            return response
        return call

    return [StructuredTool.from_function(coroutine=audited(fn), name=fn.__name__, description=description, args_schema=schema) for fn, schema, description in definitions]
