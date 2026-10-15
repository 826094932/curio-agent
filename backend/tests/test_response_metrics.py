from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AIMessageChunk
from sqlalchemy import select
from app.chat.timing import RunTiming, active_timing
from app.chat import service
from app.db.models import AgentRun
from app.db.mysql import database
from scripts.export_metrics import summarize, comparison
from tests.conftest import account


def test_monotonic_timer_and_reset():
    clock = [0.0]
    timer = RunTiming(clock=lambda: clock[0])
    with timer.span('requirements'):
        clock[0] = 0.1
    timer.note_event('token', {'text': 'temporary'})
    clock[0] = 0.2
    timer.note_event('reset', {})
    clock[0] = 0.5
    timer.note_event('token', {'text': 'final'})
    clock[0] = 0.7
    timer.finish('succeeded')
    clock[0] = 1.0
    result = timer.snapshot()
    assert result['first_token_ms'] == 500
    assert result['first_visible_token_ms'] == 100
    assert result['total_ms'] == 700
    assert result['stages'][0]['duration_ms'] == 100


async def test_token_usage_is_unknown_when_not_returned():
    timer = RunTiming()
    first, second = uuid4(), uuid4()
    await timer.models.on_chat_model_start({}, [['private prompt']], run_id=first)
    await timer.models.on_chat_model_start({}, [['private prompt']], run_id=second)
    known = SimpleNamespace(generations=[[SimpleNamespace(message=AIMessage(content='answer', usage_metadata={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15, 'input_token_details': {'cache_read': 3}}))]])
    unknown = SimpleNamespace(generations=[[SimpleNamespace(message=AIMessage(content='answer'))]])
    await timer.models.on_llm_end(known, run_id=first)
    await timer.models.on_llm_end(unknown, run_id=second)
    result = timer.snapshot()
    assert result['model_calls'] == 2 and result['usage_coverage'] == 0.5
    assert result['input_tokens'] is None and result['output_tokens'] is None
    assert 'private prompt' not in str(result)
    await timer.models.on_llm_end(known, run_id=second)
    result = timer.snapshot()
    assert result['input_tokens'] == 20 and result['output_tokens'] == 10 and result['cache_read_tokens'] == 6


class StreamAgent:
    async def astream(self, inputs, **kwargs):
        assert active_timing.get() is not None
        yield 'messages', (AIMessageChunk(content='暂时文字'), {})
        yield 'updates', {'model': {'messages': [AIMessage(content='', tool_calls=[{'name': 'search_products', 'args': {}, 'id': 'temp'}])]}}
        yield 'messages', (AIMessageChunk(content='正式回答'), {})
        yield 'updates', {'model': {'messages': [AIMessage(content='正式回答')]}}


async def test_metrics_persist_replay_and_restore_in_history(client, monkeypatch):
    headers = await account(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def extract(*args): return {}
    monkeypatch.setattr(service, 'extract_requirements', extract)
    monkeypatch.setattr(service, 'build_agent', lambda tools: StreamAgent())
    body = {'session_id': session, 'request_id': 'metrics-request-001', 'message': '你好'}
    response = await client.post('/api/v1/chat/stream', headers=headers, json=body)
    assert 'event: timings' in response.text and 'event: done' in response.text
    stored = (await client.get('/api/v1/runs/metrics-request-001', headers=headers)).json()['result']
    metrics = stored['timings']
    assert metrics['status'] == 'succeeded'
    assert metrics['first_visible_token_ms'] <= metrics['first_token_ms'] <= metrics['answer_ready_ms'] <= metrics['total_ms']
    assert {stage['name'] for stage in metrics['stages']} == {'prepare', 'memory_load', 'requirements', 'agent_loop', 'save_result'}
    history = (await client.get(f'/api/v1/sessions/{session}/messages?limit=1', headers=headers)).json()['items']
    assert history[0]['timings'] == metrics
    replay = await client.post('/api/v1/chat', headers=headers, json=body)
    assert replay.json()['result']['timings'] == metrics
    assert active_timing.get() is None
    other = await account(client, 'bob@example.com')
    assert (await client.get('/api/v1/runs/metrics-request-001', headers=other)).status_code == 404


async def test_failure_metrics_are_saved(client, monkeypatch):
    headers = await account(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def fail(*args): raise TimeoutError()
    monkeypatch.setattr(service, 'extract_requirements', fail)
    response = await client.post('/api/v1/chat', headers=headers, json={'session_id': session, 'request_id': 'failed-metrics-001', 'message': '你好'})
    assert response.status_code == 502
    result = (await client.get('/api/v1/runs/failed-metrics-001', headers=headers)).json()
    assert result['result']['timings']['status'] == 'failed'
    assert result['result']['timings']['first_token_ms'] is None
    assert active_timing.get() is None


def test_compare_only_same_case_context_and_web_mode():
    base = {'label': 'baseline', 'code_version': 'a', 'config_hash': 'cfg', 'model': 'model',
            'case_hash': 'case', 'context_hash': 'context', 'web_search_enabled': True, 'web_status': 'searched',
            'status': 'succeeded', 'total_ms': 1000, 'first_token_ms': 500, 'model_calls': 2,
            'tool_calls': 2, 'tool_errors': 0, 'input_tokens': 100, 'output_tokens': 20}
    improved = {**base, 'label': 'optimized', 'code_version': 'b', 'total_ms': 800, 'first_token_ms': 300}
    result = comparison(summarize([base]), summarize([improved]))
    assert result[0]['metrics']['total_p50_ms']['change_percent'] == -20
    assert result[0]['small_sample']
    assert not comparison(summarize([base]), summarize([{**improved, 'web_status': 'cached'}]))
    assert not comparison(summarize([base]), summarize([{**improved, 'case_hash': 'other'}]))


async def test_local_fallback_captures_tool_time(client, monkeypatch):
    from app.products import service as products
    headers = await account(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def extract(*args): return {'category': 'phone'}
    async def search(*args): return {'items': [], 'sources': [], 'active_count': 0}
    monkeypatch.setattr(service, 'extract_requirements', extract)
    monkeypatch.setattr(products, 'search', search)
    response = await client.post('/api/v1/chat', headers=headers, json={'session_id': session, 'request_id': 'local-metrics-001', 'message': '推荐手机'})
    metrics = response.json()['timings']
    assert metrics['tool_calls'] == 1 and metrics['tools'][0]['name'] == 'search_products'
    assert metrics['tool_errors'] == 0 and metrics['constraint_pass'] is None
    assert metrics['answer_characters'] > 0
