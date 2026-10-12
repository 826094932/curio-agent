from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from sqlalchemy import func, select, update

from app.agent.tools import build_tools
from app.chat import service as chat_service
from app.chat.memory import load_memory
from app.chat.schemas import ChatInput
from app.config import settings
from app.db.models import Message, Product, SessionContext, WebEvidence, WebSearchCache, now
from app.db.mysql import database
from app.errors import AppError
from app.products import service as products
from app.web_search import service as web
from tests.conftest import account


def payload(content=None):
    return {'results': [{'title': '示例手机 官方规格', 'url': 'https://www.apple.com/cn/test-phone/?utm_source=test',
                         'content': content or '示例手机的官方说明：此页面包含屏幕、续航和存储配置等选购信息。价格需要以具体地区、容量和购买页面为准，以下摘要仅用于测试。',
                         'score': 0.9}], 'usage': {'credits': 1}}


async def user_id(client, email='alice@example.com'):
    headers = await account(client, email)
    return (await client.get('/api/v1/users/me', headers=headers)).json()['id'], headers


async def ignore(*args):
    pass


def test_defaults_and_idempotency():
    data = ChatInput(session_id='session', request_id='request-001', message='推荐手机')
    assert data.web_search is False
    assert chat_service.fingerprint(data) != chat_service.fingerprint(data.model_copy(update={'web_search': True}))


def test_result_quality_and_links():
    data = payload()
    data['results'] += [*data['results'], {'title': 'spam', 'url': 'javascript:alert(1)', 'content': 'a' * 100, 'score': 1},
                        {'title': 'low', 'url': 'https://example.com', 'content': 'a' * 100, 'score': 0.1}]
    clean = web.clean_results(data)
    assert len(clean) == 1
    assert clean[0]['source_kind'] == 'official_domain'
    assert 'utm_' not in clean[0]['url']
    for url in ('http://127.0.0.1/path', 'https://localhost/path', 'https://user:pass@example.com',
                'https://example.com/?api_key=private', 'file:///secret'):
        assert web.normalize_url(url) is None


async def test_saved_cache_refresh_and_user_isolation(client, monkeypatch):
    owner, _ = await user_id(client)
    calls = []
    async def search(query):
        calls.append(query)
        return payload()
    monkeypatch.setattr(web, 'tavily_search', search)
    state = {'category': 'phone', 'budget_max': 3000}
    first = await web.search_and_save(owner, '示例手机 3000元', state)
    assert first['status'] == 'searched' and first['saved_count'] == 1
    second = await web.search_and_save(owner, '示例手机 3000元', state)
    assert second['status'] == 'cached' and second['items'][0]['cached']
    assert len(calls) == 1
    async with database.session() as db:
        await db.execute(update(WebSearchCache).values(expires_at=now() - timedelta(hours=1)))
        await db.commit()
    await web.search_and_save(owner, '示例手机 3000元', state)
    assert len(calls) == 2
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(WebEvidence)) == 1
        assert await db.scalar(select(func.count()).select_from(Product)) == 0
        await db.execute(update(WebSearchCache).values(expires_at=now() - timedelta(hours=1)))
        await db.commit()
    async def changed(query):
        calls.append(query)
        return payload('更新后的官方页面：示例手机现在提供新的存储配置选项，屏幕信息有补充，购买时仍应核对地区、配置、日期和价格信息。')
    monkeypatch.setattr(web, 'tavily_search', changed)
    updated = await web.search_and_save(owner, '示例手机 3000元', state)
    assert updated['items'][0]['id'] != first['items'][0]['id']
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(WebEvidence)) == 2
    other, _ = await user_id(client, 'bob@example.com')
    separate = await web.search_and_save(other, '示例手机 3000元', state)
    assert separate['status'] == 'searched'
    assert separate['items'][0]['id'] != updated['items'][0]['id']
    # 相同查询，但预算不同，不误用先前证据缓存。
    changed_scope = await web.search_and_save(owner, '示例手机 3000元', {'category': 'phone', 'budget_max': 1000})
    assert changed_scope['status'] == 'searched'


async def test_failure_uses_marked_old_cache(client, monkeypatch):
    owner, _ = await user_id(client)
    async def search(query): return payload()
    monkeypatch.setattr(web, 'tavily_search', search)
    await web.search_and_save(owner, '示例手机', {})
    async with database.session() as db:
        await db.execute(update(WebSearchCache).values(expires_at=now() - timedelta(days=2)))
        await db.execute(update(WebEvidence).values(fetched_at=now() - timedelta(days=2)))
        await db.commit()
    async def failed(query): raise AppError(503, 'WEB_SEARCH_QUOTA', '联网额度不足')
    monkeypatch.setattr(web, 'tavily_search', failed)
    result = await web.search_and_save(owner, '示例手机', {})
    assert result['status'] == 'stale_cache' and result['items'][0]['is_stale']
    assert result['warning'] == '联网额度不足'


async def test_storage_failure_keeps_fresh_evidence(client, monkeypatch):
    owner, _ = await user_id(client)
    async def search(query): return payload()
    async def failed(*args):
        from sqlalchemy.exc import OperationalError
        raise OperationalError('hidden statement', {}, Exception('hidden password'))
    monkeypatch.setattr(web, 'tavily_search', search)
    monkeypatch.setattr(web, 'upsert', failed)
    result = await web.search_and_save(owner, '示例手机', {})
    assert result['status'] == 'searched' and result['saved_count'] == 0
    assert not result['items'][0]['persisted'] and '保存失败' in result['warning']
    assert 'password' not in str(result)


@pytest.mark.parametrize('status,code', [(401, 'WEB_SEARCH_AUTH_FAILED'), (429, 'WEB_SEARCH_QUOTA'), (432, 'WEB_SEARCH_QUOTA'), (500, 'WEB_SEARCH_UNAVAILABLE')])
async def test_api_errors_are_redacted(monkeypatch, status, code):
    original = httpx.AsyncClient
    def handler(request):
        assert request.headers['Authorization'] == 'Bearer fake-key'
        return httpx.Response(status, json={'error': 'fake-key private details'})
    monkeypatch.setattr(settings, 'tavily_api_key', SecretStr('fake-key'))
    monkeypatch.setattr(web.httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    with pytest.raises(AppError) as error:
        await web.tavily_search('示例手机')
    assert error.value.code == code
    assert 'fake-key' not in error.value.message


async def test_missing_key_does_not_break_local_mode(client, monkeypatch):
    owner, _ = await user_id(client)
    monkeypatch.setattr(settings, 'tavily_api_key', SecretStr(''))
    result = await web.search_and_save(owner, '示例手机', {})
    assert result['status'] == 'unavailable' and result['error'] == 'WEB_SEARCH_NOT_CONFIGURED'


def test_disabled_tool_is_absent():
    tools = build_tools('user', 'run', {}, [], [], False, ignore)
    assert 'search_web' not in [tool.name for tool in tools]


class EvidenceAgent:
    def __init__(self, check): self.check = check
    async def astream(self, inputs, **kwargs):
        self.check(inputs)
        yield 'updates', {'model': {'messages': [AIMessage(content='依据工具结果给出推荐，并注明来源及待核验条件。')]}}


async def setup_chat(client, monkeypatch, *, local=False, online=True):
    owner, headers = await user_id(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def extract(previous, message): return {'category': 'phone', 'budget_max': 3000}
    async def search(*args):
        items = [{'id': 'local-phone', 'category': 'phone', 'brand': 'Example', 'name': '本地手机',
                  'specs': {}, 'price': {'final_price': '2000'}}] if local else []
        return {'items': items, 'sources': [], 'active_count': len(items)}
    monkeypatch.setattr(chat_service, 'extract_requirements', extract)
    monkeypatch.setattr(products, 'search', search)
    body = {'session_id': session, 'request_id': 'web-request-001', 'message': '推荐3000元的手机', 'web_search': online}
    return headers, body


async def test_off_empty_database_does_not_search(client, monkeypatch):
    headers, body = await setup_chat(client, monkeypatch, online=False)
    async def forbidden(*args): raise AssertionError('off mode must never search or read web cache')
    monkeypatch.setattr(web, 'search_and_save', forbidden)
    response = await client.post('/api/v1/chat', json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()['web_search']['status'] == 'disabled'
    assert '尚未' in response.json()['answer'] or '没有已启用' in response.json()['answer']


async def test_local_hit_blocks_web_even_when_model_requests_it(client, monkeypatch):
    headers, body = await setup_chat(client, monkeypatch, local=True)
    async def forbidden(*args): raise AssertionError('local hit must not call Tavily/cache')
    monkeypatch.setattr(web, 'search_and_save', forbidden)
    class Agent:
        def __init__(self, tools): self.tools = tools
        async def astream(self, inputs, **kwargs):
            tool = next(t for t in self.tools if t.name == 'search_web')
            response = await tool.ainvoke({'query': '手机'})
            assert response['data']['status'] == 'local'
            yield 'updates', {'model': {'messages': [AIMessage(content='根据本地商品推荐。')]}}
    monkeypatch.setattr(chat_service, 'build_agent', lambda tools, **kwargs: Agent(tools))
    response = await client.post('/api/v1/chat', json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()['web_search']['status'] == 'local'


async def test_empty_local_database_searches_and_exposes_sources(client, monkeypatch):
    headers, body = await setup_chat(client, monkeypatch)
    calls = []
    async def search(query): calls.append(query); return payload()
    monkeypatch.setattr(web, 'tavily_search', search)
    def check(inputs):
        assert any('web:' in str(m.content) for m in inputs['messages'])
    monkeypatch.setattr(chat_service, 'build_agent', lambda tools, **kwargs: EvidenceAgent(check))
    response = await client.post('/api/v1/chat/stream', json=body, headers=headers)
    assert 'event: web_search' in response.text and 'event: done' in response.text
    run = (await client.get('/api/v1/runs/web-request-001', headers=headers)).json()
    result = run['result']
    assert run['status'] == 'succeeded'
    assert len(calls) == 1 and result['web_search']['saved_count'] == 1
    assert result['sources'][0]['persisted'] and result['sources'][0]['source_type'] == 'web'
    replay = await client.post('/api/v1/chat', json=body, headers=headers)
    assert replay.json()['result']['web_search']['saved_count'] == 1 and len(calls) == 1
    conflict = await client.post('/api/v1/chat', json={**body, 'web_search': False}, headers=headers)
    assert conflict.status_code == 409


async def test_off_context_excludes_online_answers(client):
    owner, headers = await user_id(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async with database.session() as db:
        db.add_all([Message(session_id=session, role='user', content='买手机'),
                    Message(session_id=session, role='assistant', content='WEB_ONLY_SECRET_FACT', web_search=True),
                    Message(session_id=session, role='assistant', content='LOCAL_FACT')])
        await db.commit()
        context = await db.get(SessionContext, session)
        off, _, _ = await load_memory(db, context)
        on, _, _ = await load_memory(db, context, web_search=True)
        assert not any('WEB_ONLY' in m.content for m in off)
        assert any('LOCAL_FACT' in m.content for m in off)
        assert any('WEB_ONLY' in m.content for m in on)
