import asyncio
import pytest
from sqlalchemy import select
from langchain_core.messages import AIMessage, AIMessageChunk
from app.db.models import AgentRun, SessionContext, User, Message, AuthSession
from app.db.mysql import database
from app.chat import service
from app.chat.schemas import ChatInput
from app.errors import AppError
from tests.conftest import account


async def test_auth_rotation_and_logout(client):
    headers = await account(client)
    assert (await client.get('/api/v1/users/me', headers=headers)).status_code == 200
    original = client.cookies.get('refresh_token')
    refreshed = await client.post('/api/v1/auth/refresh')
    assert refreshed.status_code == 200
    assert client.cookies.get('refresh_token') != original
    # 已消费的 refresh token 不能重用。
    replay = await client.post('/api/v1/auth/refresh', headers={'Cookie': f'refresh_token={original}'})
    assert replay.status_code == 401
    assert (await client.post('/api/v1/auth/logout')).status_code == 200
    assert (await client.post('/api/v1/auth/refresh')).status_code == 401
    async with database.session() as db:
        user = await db.scalar(select(User))
        assert user.password_hash.startswith('$argon2')
        stored = (await db.scalars(select(AuthSession))).all()
        assert all(row.refresh_token_hash != original for row in stored)


async def test_cookie_origin_and_admin(client):
    headers = await account(client)
    response = await client.post('/api/v1/auth/refresh', headers={'Origin': 'https://attacker.invalid'})
    assert response.status_code == 403
    assert (await client.post('/api/v1/products/import', headers=headers, json=[])).status_code == 403


async def test_session_owner_isolation(client):
    alice = await account(client)
    session = (await client.post('/api/v1/sessions', headers=alice)).json()
    bob = await account(client, 'bob@example.com')
    path = '/api/v1/sessions/' + session['id']
    assert (await client.get(path + '/messages', headers=bob)).status_code == 404
    assert (await client.patch(path, headers=bob, json={'title': 'hacked'})).status_code == 404
    assert (await client.delete(path, headers=bob)).status_code == 404
    assert (await client.post('/api/v1/chat', headers=bob, json={'session_id': session['id'], 'request_id': 'request-owner-test', 'message': 'test'})).status_code == 404
    assert (await client.get('/api/v1/sessions', headers=bob)).json() == []


async def test_claim_idempotency_and_conflict(client):
    headers = await account(client)
    session_id = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    user_id = (await client.get('/api/v1/users/me', headers=headers)).json()['id']
    data = ChatInput(session_id=session_id, request_id='claim-request-001', message='买手机')
    run, fresh = await service.prepare(user_id, data)
    assert fresh
    same, fresh = await service.prepare(user_id, data)
    assert not fresh and same.id == run.id
    with pytest.raises(AppError) as error:
        await service.prepare(user_id, data.model_copy(update={'request_id': 'claim-request-002'}))
    assert error.value.code == 'SESSION_BUSY'
    with pytest.raises(AppError) as error:
        await service.prepare(user_id, data.model_copy(update={'message': 'different'}))
    assert error.value.code == 'REQUEST_ID_CONFLICT'
    await service.fail(run.id, session_id, 'TEST_CANCEL')
    async with database.session() as db:
        assert (await db.get(SessionContext, session_id)).active_run_id is None
        assert len((await db.scalars(select(Message))).all()) == 1


class FakeAgent:
    async def astream(self, inputs, **kwargs):
        assert any('手机' in str(message.content) for message in inputs['messages'])
        yield 'messages', (AIMessageChunk(content='临时过渡语'), {})
        yield 'updates', {'model': {'messages': [AIMessage(content='临时过渡语', tool_calls=[{'name': 'search_products', 'args': {}, 'id': 'test-call'}])]}}
        for chunk in ['暂无', '商品资料。']:
            yield 'messages', (AIMessageChunk(content=chunk), {})
        yield 'updates', {'model': {'messages': [AIMessage(content='暂无商品资料。')]}}


async def test_stream_persistence_replay_and_history(client, monkeypatch):
    headers = await account(client)
    session_id = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def extract(previous, message):
        return {**previous, 'category': 'phone', 'budget_max': 3000}
    monkeypatch.setattr(service, 'extract_requirements', extract)
    monkeypatch.setattr(service, 'build_agent', lambda tools: FakeAgent())
    body = {'session_id': session_id, 'request_id': 'stream-request-001', 'message': '3000 元买手机'}
    response = await client.post('/api/v1/chat/stream', json=body, headers=headers)
    assert response.status_code == 200
    assert 'event: token' in response.text and 'event: done' in response.text
    result = (await client.get('/api/v1/runs/stream-request-001', headers=headers)).json()
    assert result['status'] == 'succeeded'
    assert result['result']['answer'] == '暂无商品资料。'
    assert (await client.post('/api/v1/chat/stream', json=body, headers=headers)).text.count('event: result') == 1
    messages = (await client.get(f'/api/v1/sessions/{session_id}/messages', headers=headers)).json()['items']
    assert len(messages) == 2
    async with database.session() as db:
        context = await db.get(SessionContext, session_id)
        assert context.state_version == 1 and context.active_run_id is None
    bob = await account(client, 'bob@example.com')
    assert (await client.get('/api/v1/runs/stream-request-001', headers=bob)).status_code == 404
    recommendation = result['result']['recommendation_id']
    assert (await client.get(f'/api/v1/recommendations/{recommendation}', headers=bob)).status_code == 404
    assert (await client.post('/api/v1/feedback', headers=bob, json={'recommendation_id': recommendation, 'rating': 5})).status_code == 404


async def test_failed_generation_retains_user_message(client, monkeypatch):
    headers = await account(client)
    session_id = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def fail_extract(*args):
        raise TimeoutError()
    monkeypatch.setattr(service, 'extract_requirements', fail_extract)
    response = await client.post('/api/v1/chat', headers=headers, json={'session_id': session_id, 'request_id': 'failure-request-001', 'message': '买手机'})
    assert response.status_code == 502
    async with database.session() as db:
        assert (await db.get(SessionContext, session_id)).active_run_id is None
        assert (await db.scalar(select(AgentRun))).status == 'failed'
        assert len((await db.scalars(select(Message))).all()) == 1


async def test_cancel_releases_claim(client, monkeypatch):
    headers = await account(client)
    session_id = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    user_id = (await client.get('/api/v1/users/me', headers=headers)).json()['id']
    data = ChatInput(session_id=session_id, request_id='cancel-request-001', message='买手机')
    run, _ = await service.prepare(user_id, data)
    started = asyncio.Event()
    async def blocked(*args):
        started.set()
        await asyncio.Event().wait()
    async def ignore(*args):
        pass
    monkeypatch.setattr(service, 'extract_requirements', blocked)
    task = asyncio.create_task(service.execute(run, data, ignore))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with database.session() as db:
        assert (await db.get(SessionContext, session_id)).active_run_id is None
        assert (await db.get(AgentRun, run.id)).error_code == 'CANCELLED'
