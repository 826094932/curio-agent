"""Export recorded runs and compare matching questions/modes; never calls a model."""
import argparse
import asyncio
import csv
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def percentile(values, fraction):
    return sorted(values)[max(0, math.ceil(len(values) * fraction) - 1)] if values else None


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        key = (row.get('label'), row.get('code_version'), row.get('config_hash'), row.get('model'),
               row.get('case_hash'), row.get('context_hash'), row.get('web_search_enabled'), row.get('web_status'))
        groups[key].append(row)
    result = []
    for key, entries in groups.items():
        successful = [r for r in entries if r['status'] == 'succeeded']
        durations = [r['total_ms'] for r in successful]
        first = [r['first_token_ms'] for r in successful if r.get('first_token_ms') is not None]
        tools = sum(r.get('tool_calls', 0) for r in entries)
        errors = sum(r.get('tool_errors', 0) for r in entries)
        fields = ('label', 'code_version', 'config_hash', 'model', 'case_hash', 'context_hash', 'web_search_enabled', 'web_status')
        result.append({**dict(zip(fields, key)), 'runs': len(entries), 'success_rate': len(successful) / len(entries),
                       'total_p50_ms': statistics.median(durations) if durations else None,
                       'total_p95_ms': percentile(durations, .95),
                       'first_token_p50_ms': statistics.median(first) if first else None,
                       'tool_success_rate': (tools - errors) / tools if tools else None,
                       'model_calls_mean': statistics.mean(r.get('model_calls', 0) for r in entries),
                       'input_tokens_mean': statistics.mean(r['input_tokens'] for r in entries if r.get('input_tokens') is not None) if any(r.get('input_tokens') is not None for r in entries) else None,
                       'output_tokens_mean': statistics.mean(r['output_tokens'] for r in entries if r.get('output_tokens') is not None) if any(r.get('output_tokens') is not None for r in entries) else None,
                       'small_sample': len(successful) < 20})
    return result


def comparison(before, after):
    # Version/label may change; question, context, model, settings and web/cache mode must match.
    fields = ('config_hash', 'model', 'case_hash', 'context_hash', 'web_search_enabled', 'web_status')
    old = defaultdict(list)
    for row in before:
        old[tuple(row.get(field) for field in fields)].append(row)
    result = []
    for row in after:
        candidates = old[tuple(row.get(field) for field in fields)]
        if len(candidates) != 1:
            continue
        baseline = candidates[0]
        metrics = {}
        for field in ('total_p50_ms', 'total_p95_ms', 'first_token_p50_ms', 'model_calls_mean', 'input_tokens_mean', 'output_tokens_mean', 'success_rate'):
            a, b = baseline.get(field), row.get(field)
            metrics[field] = {'before': a, 'after': b,
                              'delta': b - a if isinstance(a, (float, int)) and isinstance(b, (float, int)) else None,
                              'change_percent': (b - a) / a * 100 if isinstance(a, (float, int)) and a and isinstance(b, (float, int)) else None}
        result.append({'case_hash': row['case_hash'], 'before_label': baseline['label'], 'after_label': row['label'],
                       'before_runs': baseline['runs'], 'after_runs': row['runs'], 'small_sample': baseline['small_sample'] or row['small_sample'], 'metrics': metrics})
    return result


async def read_runs(args):
    from sqlalchemy import select
    from app.db.mysql import database
    from app.db.models import AgentRun
    rows, legacy_count = [], 0
    try:
        async with database.session() as db:
            statement = select(AgentRun).order_by(AgentRun.created_at.desc()).limit(args.limit)
            if args.user_id:
                statement = statement.where(AgentRun.user_id == args.user_id)
            runs = (await db.scalars(statement)).all()
            for run in runs:
                metrics = run.result.get('timings')
                if not metrics:
                    legacy_count += 1
                    continue
                if args.label and metrics.get('label') != args.label:
                    continue
                rows.append({'request_id': run.request_id, 'error_code': run.error_code, **metrics})
    finally:
        if database.engine:
            await database.engine.dispose()
    return rows, legacy_count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', help='输出目录；默认项目根目录 log 下的新批次')
    parser.add_argument('--label')
    parser.add_argument('--user-id')
    parser.add_argument('--limit', type=int, default=10000)
    parser.add_argument('--baseline', help='Previous summary.json path')
    args = parser.parse_args()
    if not 1 <= args.limit <= 100000:
        parser.error('--limit must be between 1 and 100000')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S-%f')
    label_hash = hashlib.sha256((args.label or 'all').encode()).hexdigest()[:8]
    out = (Path(args.output) if args.output else Path(__file__).resolve().parents[2] / 'log' / (stamp + '-response-' + label_hash)).resolve()
    if any((out / name).exists() for name in ('runs.csv', 'runs.json', 'summary.json')):
        parser.error('输出目录已有指标快照，请使用新的日期或批次目录，避免覆盖历史基线。')
    rows, legacy = asyncio.run(read_runs(args))
    out.mkdir(parents=True, exist_ok=True)
    summary = {'exported_at': datetime.now(timezone.utc).isoformat(), 'runs': len(rows), 'legacy_runs_without_metrics': legacy,
               'execution_success_rate': sum(row['status'] == 'succeeded' for row in rows) / len(rows) if rows else None,
               'groups': summarize(rows)}
    (out / 'runs.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    columns = ['request_id', 'started_at', 'status', 'error_code', 'label', 'code_version', 'config_hash', 'model', 'case_hash', 'context_hash',
               'web_search_enabled', 'web_status', 'cache_hit', 'proxy_enabled', 'first_token_ms', 'total_ms', 'answer_ready_ms',
               'model_calls', 'model_errors', 'tool_calls', 'tool_errors', 'input_tokens', 'output_tokens', 'cache_read_tokens',
               'usage_coverage', 'answer_characters', 'source_count', 'product_count', 'constraint_pass']
    with (out / 'runs.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    if args.baseline:
        before = json.loads(Path(args.baseline).read_text(encoding='utf-8'))
        (out / 'comparison.json').write_text(json.dumps(comparison(before['groups'], summary['groups']), ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Exported {len(rows)} measured runs; skipped {legacy} legacy runs without complete metrics. Output: {out}")


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Provider/DB exception messages may contain credentials.
        print('Metrics export failed:', type(exc).__name__)
        raise SystemExit(1)
