"""Fixed local retrieval benchmark; no LLM, web API or production database writes."""
import argparse
import asyncio
import csv
import hashlib
import json
import math
import os
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')


def ratio(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


def p95(values):
    return sorted(values)[max(0, math.ceil(len(values) * .95) - 1)] if values else None


def hard_violations(item, state):
    """独立检查规格、预算与品牌，不调用被测服务的 eligible/matches。"""
    failures = []
    aliases = {'苹果': 'apple', '小米': 'xiaomi', '索尼': 'sony', '红米': 'redmi', '三星': 'samsung', '华为': 'huawei'}
    normalize_brand = lambda value: aliases.get(value.strip().casefold(), value.strip().casefold())
    if state.get('category') and item.get('category') != state['category']:
        failures.append('category')
    if normalize_brand(item.get('brand', '')) in {normalize_brand(v) for v in state.get('excluded_brands', [])}:
        failures.append('excluded_brand')
    price = (item.get('price') or {}).get('final_price')
    for key, op in [('budget_min', lambda p, b: p >= b), ('budget_max', lambda p, b: p <= b)]:
        if state.get(key) is not None and (price is None or not op(float(price), state[key])):
            failures.append(key)
    for expression, expected in state.get('hard_constraints', {}).items():
        key = expression.removesuffix('_gte').removesuffix('_lte')
        value = item.get('specs', {}).get(key)
        try:
            valid = value is not None and (float(value) >= float(expected) if expression.endswith('_gte')
                else float(value) <= float(expected) if expression.endswith('_lte') else value == expected)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            failures.append(expression)
    return failures


def judge(case, result):
    items = result.get('items') or []
    family_items = result.get('family_items') or []
    exact_ids = [p['id'] for p in items]
    returned = {p['id']: p for p in [*items, *family_items]}
    accepted = set(case['expected_ids'])
    family_gold = set(case.get('family_ids', []))
    relevant = accepted | family_gold
    top = list(returned)[:3]
    targets = case.get('target_groups')
    exact_hit = all(set(ids) & set(exact_ids) for ids in targets) if targets else None
    available = bool(targets) and all(targets)
    bad = [{'id': p['id'], 'violations': hard_violations(p, case['state'])}
           for p in returned.values() if hard_violations(p, case['state'])]
    # 型号正确性由人工标注的商品 ID 独立判定；条件检查不替代型号判定。
    correct_set = set(returned) == relevant
    return {'returned_ids': list(returned), 'exact_returned_ids': exact_ids,
            'expected_ids': sorted(accepted), 'family_expected_ids': sorted(family_gold),
            'exact_hit': exact_hit, 'all_targets_available': available,
            'family_candidate_provided': bool(set(returned) & family_gold) if family_gold else None,
            'empty': not returned, 'expected_empty': not relevant,
            'unexpected_empty': not returned if relevant else None,
            'recall_at_3': len(set(top) & relevant) / len(relevant) if relevant else None,
            'precision_at_3': len(set(top) & relevant) / len(top) if top else None,
            'violations': bad, 'returned_count': len(returned), 'violating_item_count': len(bad),
            'case_pass': correct_set and not bad}


def summarize(rows):
    successful = [r for r in rows if r['status'] == 'succeeded']
    times = [r['search_ms'] for r in successful]
    nonempty = [r for r in successful if r['returned_count']]
    groups = {}
    for group in sorted({r['group'] for r in rows}):
        entries = [r for r in rows if r['group'] == group]
        groups[group] = {'runs': len(entries), 'case_pass_rate': ratio([r.get('case_pass', False) for r in entries]),
                         'zero_result_rate': ratio([r['empty'] for r in entries if r['status'] == 'succeeded'])}
    return {'distinct_cases': len({r['case_id'] for r in rows}), 'runs': len(rows),
        'execution_success_rate': len(successful) / len(rows) if rows else None,
        'exact_requested_hit_rate': ratio([r['exact_hit'] for r in successful]),
        'available_target_hit_rate': ratio([r['exact_hit'] for r in successful if r['all_targets_available']]),
        'family_candidate_rate': ratio([r['family_candidate_provided'] for r in successful]),
        'zero_result_rate': ratio([r['empty'] for r in successful]),
        'unexpected_zero_result_rate': ratio([r['unexpected_empty'] for r in successful]),
        'hard_constraint_violation_rate': ratio([bool(r['violations']) for r in nonempty]),
        'violating_item_rate': sum(r['violating_item_count'] for r in nonempty) / sum(r['returned_count'] for r in nonempty) if nonempty else None,
        'mean_recall_at_3': ratio([r['recall_at_3'] for r in successful]),
        'mean_precision_at_3': ratio([r['precision_at_3'] for r in successful]),
        'case_pass_rate': ratio([r.get('case_pass', False) for r in rows]),
        'search_p50_ms': statistics.median(times) if times else None, 'search_p95_ms': p95(times),
        'first_token_p50_ms': None, 'first_token_p95_ms': None,
        'first_token_note': '未调用语言模型，本评测不测首字等待或最终回答质量。',
        'denominators': {'exact_requests': sum(r['exact_hit'] is not None for r in successful),
                         'available_target_requests': sum(r['all_targets_available'] for r in successful),
                         'family_opportunities': sum(r['family_candidate_provided'] is not None for r in successful),
                         'nonempty_requests': len(nonempty), 'expected_empty_requests': sum(r['expected_empty'] for r in successful)},
        'failed_cases': sorted({r['case_id'] for r in rows if not r.get('case_pass')}), 'groups': groups,
        'rate_unit': '固定查询等次数重复的测试执行；不是生产请求的统计分布。'}


async def evaluate(args, cases, out):
    # 在导入任何模型库前禁用下载和托管 tracing。
    for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
        os.environ[key] = '1'
    os.environ['LANGSMITH_TRACING'] = 'false'
    os.environ['LANGCHAIN_TRACING_V2'] = 'false'
    project = Path(args.project).resolve()
    sys.path.insert(0, str(project / 'backend'))
    from sqlalchemy import select, event
    from app.config import settings
    from app.db.mysql import database
    from app.db.models import Product, Price
    from app.db.chroma import VectorStore
    from app.products import service
    from app.products.schemas import SearchInput
    from app.ingestion.service import product_document, content_hash
    from app.chat.timing import code_version

    async def snapshot():
        async with database.session() as db:
            products = (await db.scalars(select(Product).order_by(Product.id))).all()
            prices = (await db.scalars(select(Price).order_by(Price.id))).all()
        return products, {'products': [{c.name: getattr(p, c.name) for c in Product.__table__.columns} for p in products],
                          'prices': [{c.name: getattr(p, c.name) for c in Price.__table__.columns} for p in prices]}

    original_vectors = service.vectors
    start_load = perf_counter()
    try:
        products, facts = await snapshot()
        active = [p for p in products if p.status == 'active']
        active_ids = {p.id for p in active}
        for case in cases:
            gold = set(case['expected_ids']) | set(case.get('family_ids', []))
            if gold - active_ids:
                raise ValueError('评测标注的商品已变化，请先更新 retrieval_cases.json；不自动伪造新标签。')
        save(out / 'facts.json', facts)
        print(f'Read {len(active)} active products; {len(cases)} fixed queries. Loading cached embedding offline...', flush=True)
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer(settings.embedding_model, device=settings.embedding_device, local_files_only=True)
        load_ms = round((perf_counter() - start_load) * 1000, 2)

        class MeasuredVectors(VectorStore):
            measurements = None
            def encode(self, texts):
                mark = perf_counter()
                result = super().encode(texts)
                if self.measurements is not None:
                    self.measurements['embedding_ms'] += (perf_counter() - mark) * 1000
                return result
            def query(self, *a, **kw):
                before = self.measurements['embedding_ms'] if self.measurements is not None else 0
                mark = perf_counter()
                result = super().query(*a, **kw)
                if self.measurements is not None:
                    self.measurements['chroma_ms'] += max(0, (perf_counter() - mark) * 1000 - (self.measurements['embedding_ms'] - before))
                return result

        store = MeasuredVectors(str(out / 'vectors'), model)
        service.vectors = store
        setup = perf_counter()
        if active:
            documents = [product_document(p) for p in active]
            metadatas = [{'product_id': p.id, 'category': p.category_code, 'brand': p.brand,
                          'source_url': p.source_url, 'content_hash': content_hash([text, p.source_url])}
                         for p, text in zip(active, documents)]
            store.collection('product_knowledge').upsert(ids=[p.id for p in active],
                         documents=documents, metadatas=metadatas, embeddings=store.encode(documents))
        store.query('product_knowledge', '电子产品选购', limit=3)
        setup_ms = round((perf_counter() - setup) * 1000, 2)
        current = None
        def before_cursor(conn, cursor, statement, parameters, context, many):
            if current is not None:
                context.benchmark_start = perf_counter()
        def after_cursor(conn, cursor, statement, parameters, context, many):
            if current is not None and hasattr(context, 'benchmark_start'):
                current['sql_ms'] += (perf_counter() - context.benchmark_start) * 1000
                current['sql_queries'] += 1
        event.listen(database.engine.sync_engine, 'before_cursor_execute', before_cursor)
        event.listen(database.engine.sync_engine, 'after_cursor_execute', after_cursor)
        manifest = {'scope': 'actual product search function; read-only MySQL; isolated reindexed Chroma; manually annotated state; no LLM/web calls',
                    'version': args.version, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'code_version': code_version(), 'dataset_sha256': digest(cases), 'facts_sha256': digest(facts),
                    'active_products': len(active), 'repeat': args.repeat, 'top_k': 3,
                    'embedding_model': settings.embedding_model, 'embedding_device': settings.embedding_device,
                    'offline_model_load_and_snapshot_ms': load_ms, 'private_index_build_and_warm_ms': setup_ms,
                    'latency_mode': 'warm retrieval; excludes model loading/index preparation',
                    'family_feature_implemented': False, 'api_calls': 0}
        save(out / 'manifest.json', manifest)
        rows = []
        for case in cases:
            for repeat in range(args.repeat):
                current = {'sql_ms': 0.0, 'sql_queries': 0, 'embedding_ms': 0.0, 'chroma_ms': 0.0}
                store.measurements = current
                started = perf_counter()
                row = {'case_id': case['id'], 'group': case['group'], 'repeat': repeat + 1, 'query': case['query'],
                       'state': case['state'], 'status': 'succeeded'}
                try:
                    result = await asyncio.wait_for(service.search(SearchInput(query=case['query'], category=case['state'].get('category'), top_k=3), case['state']), 45)
                    row.update(judge(case, result), retrieval_mode=result.get('retrieval_mode'), reason=result.get('reason'))
                except Exception as exc:
                    row.update(status='failed', error_type=type(exc).__name__, error_code=getattr(exc, 'code', None), case_pass=False)
                row['search_ms'] = round((perf_counter() - started) * 1000, 2)
                row.update({k: round(v, 2) if isinstance(v, float) else v for k, v in current.items()})
                current = None
                store.measurements = None
                rows.append(row)
                with (out / 'runs.jsonl').open('a', encoding='utf-8') as handle:
                    handle.write(json.dumps(row, ensure_ascii=False) + '\n')
                if repeat == 0:
                    print(f"{case['id']}: {row['status']}, IDs={row.get('returned_ids', [])}, {row['search_ms']:.0f}ms", flush=True)
        event.remove(database.engine.sync_engine, 'before_cursor_execute', before_cursor)
        event.remove(database.engine.sync_engine, 'after_cursor_execute', after_cursor)
        _, final_facts = await snapshot()
        manifest['facts_unchanged_during_run'] = digest(final_facts) == digest(facts)
        save(out / 'manifest.json', manifest)
        summary = summarize(rows)
        summary['facts_unchanged_during_run'] = manifest['facts_unchanged_during_run']
        save(out / 'summary.json', summary)
        columns = ['case_id', 'group', 'repeat', 'query', 'status', 'case_pass', 'exact_hit', 'all_targets_available',
                   'family_candidate_provided', 'empty', 'expected_empty', 'unexpected_empty', 'returned_count',
                   'violating_item_count', 'recall_at_3', 'precision_at_3', 'search_ms', 'sql_ms', 'embedding_ms',
                   'chroma_ms', 'sql_queries', 'retrieval_mode', 'reason', 'returned_ids', 'expected_ids', 'family_expected_ids', 'violations']
        with (out / 'results.csv').open('w', encoding='utf-8-sig', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for row in rows:
                writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, dict)) else value for key, value in row.items()})
        if args.baseline:
            old = Path(args.baseline)
            old_manifest = json.loads((old / 'manifest.json').read_text(encoding='utf-8'))
            old_summary = json.loads((old / 'summary.json').read_text(encoding='utf-8'))
            compatibility = {key: manifest[key] == old_manifest.get(key) for key in ('dataset_sha256', 'facts_sha256', 'embedding_model', 'embedding_device', 'top_k', 'repeat', 'latency_mode')}
            valid = all(compatibility.values()) and manifest['facts_unchanged_during_run'] and old_manifest.get('facts_unchanged_during_run')
            metrics = {}
            for key in ('exact_requested_hit_rate', 'available_target_hit_rate', 'family_candidate_rate', 'zero_result_rate', 'hard_constraint_violation_rate', 'mean_recall_at_3', 'search_p50_ms', 'search_p95_ms'):
                a, b = old_summary.get(key), summary.get(key)
                metrics[key] = {'before': a, 'after': b, 'delta': b - a if valid and isinstance(a, (int,float)) and isinstance(b,(int,float)) else None}
            save(out / 'comparison.json', {'comparable': valid, 'conditions': compatibility, 'metrics': metrics})
        print(json.dumps({'output': str(out), 'summary': summary}, ensure_ascii=True, indent=2), flush=True)
    finally:
        service.vectors = original_vectors
        if database.engine:
            await database.engine.dispose()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument('--cases', default=str(Path(__file__).with_name('retrieval_cases.json')))
    parser.add_argument('--version', default='retrieval-baseline')
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--output')
    parser.add_argument('--baseline')
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error('--repeat must be 1..20')
    cases = json.loads(Path(args.cases).read_text(encoding='utf-8'))
    if not cases or len({case['id'] for case in cases}) != len(cases):
        parser.error('评测集不能为空，且 case id 必须唯一')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    out = Path(args.output) if args.output else Path(args.project) / 'log' / (stamp + '-retrieval-' + digest(args.version)[:8])
    out = out.resolve()
    if out.exists():
        parser.error('输出目录已存在，请换一个目录，避免覆盖历史基线')
    out.mkdir(parents=True)
    try:
        asyncio.run(evaluate(args, cases, out))
    except Exception as exc:
        save(out / 'failure.json', {'type': type(exc).__name__, 'message': '评测未完成。检查本地模型缓存、数据库或数据集商品 ID；没有修改商品数据。'})
        print('Retrieval evaluation failed:', type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
