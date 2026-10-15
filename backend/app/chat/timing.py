"""Local monotonic timing; stores no prompts, credentials or webpage content."""
import hashlib
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from langchain_core.callbacks import AsyncCallbackHandler

from app.config import settings

active_timing = ContextVar('active_run_timing', default=None)


class ModelMetrics(AsyncCallbackHandler):
    def __init__(self, timer):
        self.timer = timer
        self.calls = {}

    async def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        self.calls[str(run_id)] = {'start_ms': self.timer.elapsed_ms(), 'status': 'running', 'usage': None}

    async def on_llm_end(self, response, *, run_id, **kwargs):
        call = self.calls.setdefault(str(run_id), {'start_ms': self.timer.elapsed_ms()})
        usage = None
        for group in response.generations:
            for generation in group:
                message = getattr(generation, 'message', None)
                candidate = getattr(message, 'usage_metadata', None)
                if isinstance(candidate, dict) and isinstance(candidate.get('input_tokens'), int) and isinstance(candidate.get('output_tokens'), int):
                    usage = {key: candidate[key] for key in ('input_tokens', 'output_tokens')}
                    usage['cache_read_tokens'] = (candidate.get('input_token_details') or {}).get('cache_read')
                    break
        call.update(status='succeeded', duration_ms=round(self.timer.elapsed_ms() - call['start_ms'], 2), usage=usage)

    async def on_llm_error(self, error, *, run_id, **kwargs):
        call = self.calls.setdefault(str(run_id), {'start_ms': self.timer.elapsed_ms()})
        call.update(status='failed', duration_ms=round(self.timer.elapsed_ms() - call['start_ms'], 2), usage=None)

    def snapshot(self):
        calls = list(self.calls.values())
        measured = [call['usage'] for call in calls if call.get('usage')]
        complete = bool(calls) and len(measured) == len(calls)
        cache_known = complete and all(isinstance(usage.get('cache_read_tokens'), int) for usage in measured)
        return {'model_calls': len(calls), 'model_errors': sum(call['status'] == 'failed' for call in calls),
                'input_tokens': sum(u['input_tokens'] for u in measured) if complete else None,
                'output_tokens': sum(u['output_tokens'] for u in measured) if complete else None,
                'cache_read_tokens': sum(u['cache_read_tokens'] for u in measured) if cache_known else None,
                'usage_coverage': round(len(measured) / len(calls), 4) if calls else None,
                'model_timings': [{k: v for k, v in call.items() if k != 'usage'} for call in calls]}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:16]


@lru_cache(maxsize=1)
def code_version():
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*.py')):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b'\r\n', b'\n'))
    return digest.hexdigest()[:12]


class RunTiming:
    def __init__(self, clock=None):
        self.clock = clock or perf_counter
        self.start = self.clock()
        self.end = None
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.first_visible_token_ms = None
        self.first_token_ms = None
        self.answer_ready_ms = None
        self.stages, self.tools = [], []
        self.case_hash = None
        self.context_hash = None
        self.status = 'running'
        self.models = ModelMetrics(self)
        self.answer_characters = 0
        self.source_count = 0
        self.product_count = 0
        self.constraint_pass = None

    def elapsed_ms(self):
        return round(max(0, (self.clock() - self.start) * 1000), 2)

    def set_case(self, message, enabled):
        self.case_hash = fingerprint([message.strip(), enabled])

    def set_context(self, state, messages, summary):
        # IDs change between identical replays; only actual model context affects this hash.
        relevant = {k: v for k, v in state.items() if not k.endswith('_ids') and k != 'recommendation_id'}
        self.context_hash = fingerprint([relevant, [(m.type, m.content) for m in messages], summary])

    @contextmanager
    def span(self, name):
        start = self.clock()
        status = 'succeeded'
        try:
            yield
        except BaseException:
            status = 'failed'
            raise
        finally:
            self.stages.append({'name': name, 'start_ms': round(max(0, (start - self.start) * 1000), 2),
                                'duration_ms': round(max(0, (self.clock() - start) * 1000), 2), 'status': status})

    def note_event(self, kind, content):
        if kind == 'reset':
            self.first_token_ms = None
        elif kind == 'token' and content.get('text'):
            elapsed = self.elapsed_ms()
            if self.first_visible_token_ms is None:
                self.first_visible_token_ms = elapsed
            if self.first_token_ms is None:
                self.first_token_ms = elapsed

    def record_tool(self, name, started_ms, duration_ms, response):
        data = response.get('data', {})
        self.tools.append({'name': name, 'start_ms': started_ms, 'duration_ms': round(duration_ms, 2),
                           'status': 'succeeded' if response.get('ok') else 'failed',
                           'cache_hit': data.get('status') in ('cached', 'stale_cache')})

    def finish(self, status):
        self.status, self.end = status, self.clock()

    def snapshot(self, web_report=None):
        report = web_report or {}
        config = {'model': settings.deepseek_model, 'embedding_model': settings.embedding_model,
                  'max_agent_steps': settings.max_agent_steps, 'request_timeout': settings.request_timeout,
                  'price_stale_hours': settings.price_stale_hours, 'web_cache_hours': settings.web_search_cache_hours,
                  'web_max_calls': settings.web_search_max_calls,
                  'proxy_enabled': bool(os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or os.getenv('HTTP_PROXY') or os.getenv('http_proxy'))}
        return {'schema_version': 1, 'label': settings.timing_label, 'code_version': code_version(),
                'config_hash': fingerprint(config), 'model': settings.deepseek_model,
                'proxy_enabled': config['proxy_enabled'],
                'started_at': self.started_at, 'status': self.status,
                'case_hash': self.case_hash, 'context_hash': self.context_hash,
                'web_search_enabled': bool(report.get('enabled')), 'web_status': report.get('status', 'disabled'),
                'cache_hit': bool(report.get('cache_hit')),
                'first_token_ms': self.first_token_ms, 'first_visible_token_ms': self.first_visible_token_ms,
                'answer_ready_ms': self.answer_ready_ms,
                'total_ms': round(max(0, ((self.end if self.end is not None else self.clock()) - self.start) * 1000), 2),
                'stages': list(self.stages), 'tools': list(self.tools),
                'tool_calls': len(self.tools), 'tool_errors': sum(t['status'] == 'failed' for t in self.tools),
                'answer_characters': self.answer_characters, 'source_count': self.source_count,
                'product_count': self.product_count, 'constraint_pass': self.constraint_pass,
                **self.models.snapshot()}
