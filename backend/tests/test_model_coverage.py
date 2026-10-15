import pytest
from sqlalchemy import select
from langchain_core.messages import AIMessage

from app.agent.tools import build_tools
from app.chat import service as chat
from app.db.models import Product, now
from app.db.mysql import database
from app.products import service as products
from app.products.matching import matches_model, models_in_message, local_coverage
from app.products.schemas import SearchInput
from app.web_search import service as web
from tests.conftest import account


def item(id, brand, model):
    return {'id': id, 'name': f'{brand} {model}', 'model': model, 'brand': brand,
            'category': 'headphone', 'specs': {'battery_hours': 30},
            'summary': '测试商品资料', 'source_url': 'https://example.org/' + id,
            'price': {}, 'retrieval_score': 0.95, 'evidence_id': 'product:' + id}


SONY = item('sony-xm5', 'Sony', 'WH-1000XM5')
BEATS = item('beats-studio', 'Beats', 'Studio Pro')
UNRELATED = [item('xiaomi-buds', 'Xiaomi', 'Buds 6'), item('airpods', 'Apple', 'AirPods 5')]
REQUESTED = ['索尼 XM5', 'Beats Studio Pro']


@pytest.mark.parametrize('requested,record,matched', [
    ('索尼 XM5', SONY, True), ('sony wh1000xm5', SONY, True),
    ('WH-1000XM5', SONY, True), ('Beats Studio Pro', BEATS, True),
    ('索尼 XM5', UNRELATED[0], False), ('Beats Studio Pro', UNRELATED[1], False),
    ('索尼 XM5', item('wrong', 'Sony', 'WH-1000XM50'), False),
    ('Beats Studio Pro', item('wrong', 'Beats', 'Studio Pro Plus'), False),
    ('iPhone 16 Pro', item('wrong', 'Apple', 'iPhone 16 Pro Max'), False),
    ('AirPods 5', item('configured', 'Apple', 'AirPods 5 USB-C'), True),
    ('iPhone 18 Pro', item('configured', 'Apple', 'iPhone 18 Pro 256GB'), True),
    ('Xiaomi 17 Ultra', item('configured', 'Xiaomi', 'Xiaomi 17 Ultra 16GB+512GB'), True),
    ('iPhone 18', item('wrong', 'Apple', 'iPhone 18 Pro 256GB'), False),
    ('AirPods 5', item('wrong', 'Apple', 'AirPods 50 USB-C'), False),
    ('iPhone 18 Pro 256GB', item('wrong', 'Apple', 'iPhone 18 Pro 512GB'), False),
])
def test_model_identity(requested, record, matched):
    assert matches_model(record, requested) is matched


def test_all_requested_models_must_be_covered():
    state = {'requested_models': REQUESTED}
    assert local_coverage(UNRELATED, state)['missing_models'] == REQUESTED
    partial = local_coverage([SONY], state)
    assert not partial['local_sufficient'] and partial['missing_models'] == ['Beats Studio Pro']
    assert local_coverage([SONY, BEATS], state)['local_sufficient']
    assert local_coverage(UNRELATED, {})['local_sufficient']
    assert models_in_message('对比索尼 XM5 / Beats Studio Pro，通勤用') == REQUESTED
    assert len(models_in_message('索尼 WH-1000XM5')) == 1


async def test_named_search_reads_all_matching_database_records(client, monkeypatch):
    async with database.session() as db:
        for record in [*UNRELATED, SONY]:
            db.add(Product(id=record['id'], category_code='headphone', brand=record['brand'],
                           model=record['model'], name=record['name'], summary=record['summary'],
                           specs=record['specs'], source='test', source_url=record['source_url'],
                           source_updated_at=now(), content_hash='test'))
        await db.commit()
    def forbidden(*args): raise AssertionError('named identity must not depend on vector nearest neighbours')
    monkeypatch.setattr(products.vectors, 'query', forbidden)
    state = {'category': 'headphone', 'requested_models': REQUESTED}
    partial = await products.search(SearchInput(query='对比索尼 XM5 / Beats Studio Pro', category='headphone'), state)
    assert [p['id'] for p in partial['items']] == [SONY['id']]
    assert not partial['local_sufficient'] and partial['missing_models'] == ['Beats Studio Pro']
    assert partial['retrieval_mode'] == 'model_match'
    async with database.session() as db:
        db.add(Product(id=BEATS['id'], category_code='headphone', brand=BEATS['brand'], model=BEATS['model'],
                       name=BEATS['name'], summary=BEATS['summary'], specs=BEATS['specs'], source='test',
                       source_url=BEATS['source_url'], source_updated_at=now(), content_hash='test'))
        await db.commit()
    complete = await products.search(SearchInput(query='对比索尼 XM5 / Beats Studio Pro', category='headphone'), state)
    assert complete['local_sufficient'] and len(complete['items']) == 2


@pytest.mark.parametrize('local,online,expected_calls,expected_missing', [
    (UNRELATED, True, 1, REQUESTED),
    ([SONY, *UNRELATED], True, 1, ['Beats Studio Pro']),
    ([SONY, BEATS, *UNRELATED], True, 0, []),
    (UNRELATED, False, 0, REQUESTED),
])
async def test_comparison_preflight_and_tool_gate_agree(client, monkeypatch, local, online, expected_calls, expected_missing):
    headers = await account(client)
    session = (await client.post('/api/v1/sessions', headers=headers)).json()['id']
    async def extract(*args): return {'category': 'headphone', 'requested_models': REQUESTED}
    async def search(*args):
        return {'items': local, 'sources': [{'id': p['evidence_id'], 'url': p['source_url'], 'text': p['summary']} for p in local], 'active_count': len(local)}
    calls = []
    async def external(*args):
        calls.append(args[1])
        return {'items': [{'id': 'web:matched', 'url': 'https://example.org/comparison', 'text': '目标型号资料', 'source_type': 'web'}],
                'status': 'searched', 'saved_count': 1, 'warning': None}
    class Agent:
        def __init__(self, tools): self.tools = tools
        async def astream(self, inputs, **kwargs):
            # 本地无关来源必须被剔除，部分匹配时不能直接返回 status: local。
            assert not any('Xiaomi Buds 6' in str(m.content) or 'Apple AirPods 5' in str(m.content) for m in inputs['messages'])
            if expected_calls:
                assert any('web:matched' in str(m.content) for m in inputs['messages'])
            elif online:
                gate = await next(t for t in self.tools if t.name == 'search_web').ainvoke({'query': '这两款耳机'})
                assert gate['data']['status'] == 'local'
            yield 'updates', {'model': {'messages': [AIMessage(content='根据匹配型号的来源进行比较。')]}}
    monkeypatch.setattr(chat, 'extract_requirements', extract)
    monkeypatch.setattr(products, 'search', search)
    monkeypatch.setattr(web, 'search_and_save', external)
    monkeypatch.setattr(chat, 'build_agent', lambda tools, **kwargs: Agent(tools))
    body = {'session_id': session, 'request_id': 'model-comparison-001',
            'message': '对比索尼 XM5 / Beats Studio Pro，通勤用', 'web_search': online}
    response = await client.post('/api/v1/chat', json=body, headers=headers)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(calls) == expected_calls
    assert result['web_search']['missing_models'] == expected_missing
    assert result['web_search']['status'] == ('searched' if expected_calls else ('local' if online else 'disabled'))


async def test_new_empty_query_does_not_reuse_old_local_candidates(client, monkeypatch):
    headers = await account(client)
    owner = (await client.get('/api/v1/users/me', headers=headers)).json()['id']
    report = {'enabled': True}
    state = {'category': 'headphone'}
    evidence = []
    async def search(data, state):
        return {'items': [SONY] if data.query == 'first' else [], 'sources': []}
    calls = []
    async def external(*args):
        calls.append(args[1])
        return {'items': [], 'status': 'empty', 'saved_count': 0, 'warning': None}
    async def emit(*args): pass
    monkeypatch.setattr(products, 'search', search)
    monkeypatch.setattr(web, 'search_and_save', external)
    tools = build_tools(owner, 'test-run', state, evidence, [], False, emit, web_search=True, web_report=report)
    find = next(t for t in tools if t.name == 'search_products')
    external_tool = next(t for t in tools if t.name == 'search_web')
    await find.ainvoke({'query': 'first'})
    await find.ainvoke({'query': 'second'})
    response = await external_tool.ainvoke({'query': 'second'})
    assert response['data']['status'] == 'empty' and calls == ['second']
