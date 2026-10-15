from types import SimpleNamespace
import json
import httpx
import pytest
from sqlalchemy import select, func, update
from pydantic import SecretStr
from app.config import settings
from app.db.models import Product, ProductUpdate, Price, WebEvidence, now
from app.db.mysql import database
from app.ingestion import updates, converter, sources
from app.products.schemas import SearchInput
from app.products import service as products
from app.web_search import service as web
from tests.conftest import account
from tests.test_products import TinyEmbedding
from app.db.chroma import VectorStore

TEXT = 'AirPods 5 USB-C\nAirPods 5 USB-C 是本页的单一产品。电池续航 30 小时。重量 5 克。这是一份测试官网资料，只用于检查商品规格提取，不是实际商品参数。价格和库存需要另行核实，不应自动入库。'
URL = 'https://www.apple.com/airpods-test/specs/'


async def admin(client, monkeypatch):
    monkeypatch.setattr(settings, 'admin_emails', ['admin@example.com'])
    headers = await account(client, 'admin@example.com')
    return headers, (await client.get('/api/v1/users/me', headers=headers)).json()['id']


async def seed_source(client, headers, *, url=URL, content=TEXT):
    owner = (await client.get('/api/v1/users/me', headers=headers)).json()['id']
    async with database.session() as db:
        row = WebEvidence(user_id=owner, url=url, title='测试产品官网', content=content,
                          content_hash=web.digest(content), relevance_score=.9,
                          source_kind='official_domain', category='headphone', fetched_at=now())
        db.add(row)
        await db.flush()
        await updates.enqueue(db, [row])
        await db.commit()
    records = await updates.list_records('', '', 1, 20)
    return records['items'][0]['id']


def fake_extraction(monkeypatch):
    calls = []
    async def fetch(url):
        calls.append(url)
        return {'source_url': url, 'title': '测试产品官网', 'text': TEXT, 'json_ld': [],
                'captured_at': now().isoformat() + 'Z'}
    class Extractor:
        def with_structured_output(self, *args, **kwargs): return self
        async def ainvoke(self, messages):
            return converter.ExtractedProduct(category_code='headphone', model='AirPods 5 USB-C',
                model_evidence='AirPods 5 USB-C 是本页的单一产品。',
                summary_evidence='AirPods 5 USB-C 是本页的单一产品。', specs=[
                    converter.ExtractedSpec(key='battery_hours', value=30, evidence='电池续航 30 小时。'),
                    converter.ExtractedSpec(key='weight_g', value=5, evidence='重量 5 克。')])
    monkeypatch.setattr(updates, 'fetch_product_page', fetch)
    monkeypatch.setattr(converter, 'create_model', lambda: Extractor())
    return calls


async def prepare(client, headers, id):
    data = await updates.detail(id)
    response = await client.post(f'/api/v1/product-updates/{id}/prepare', headers=headers,
                                 json={'version': data['version']})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'draft', response.text
    return response.json()


async def approve(client, headers, draft, replacements=None):
    return await client.post(f"/api/v1/product-updates/{draft['id']}/approve", headers=headers,
        json={'version': draft['version'], 'target_hash': draft['preview']['target_hash'],
              'replace_fields': replacements or []})


async def test_search_enqueues_without_products_and_deduplicates(client, monkeypatch):
    headers, owner = await admin(client, monkeypatch)
    async def search(query):
        return {'results': [{'url': URL, 'title': '官网产品', 'content': TEXT, 'score': .9}]}
    monkeypatch.setattr(web, 'tavily_search', search)
    first = await web.search_and_save(owner, '第一条检索', {'category': 'headphone'})
    assert first['saved_count'] == 1 and first['update_count'] == 1
    assert (await web.search_and_save(owner, '另一条检索', {'category': 'headphone'}))['update_count'] == 0
    other_headers = await account(client, 'other@example.com')
    other = (await client.get('/api/v1/users/me', headers=other_headers)).json()['id']
    await web.search_and_save(other, '同一公开资料', {})
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(ProductUpdate)) == 1
        assert await db.scalar(select(func.count()).select_from(WebEvidence)) == 2
        assert await db.scalar(select(func.count()).select_from(Product)) == 0
        item = await db.scalar(select(ProductUpdate))
        assert 'user_id' not in updates.summary(item)
    response = await client.post('/api/v1/product-updates/sync', headers=headers)
    assert response.json()['added_count'] == 0


async def test_permissions(client, monkeypatch):
    await admin(client, monkeypatch)
    assert (await client.get('/api/v1/product-updates')).status_code == 401
    headers = await account(client)
    assert (await client.get('/api/v1/product-updates', headers=headers)).status_code == 403
    for action in ('sync', 'missing/prepare', 'missing/approve', 'missing/retry-index', 'missing/reject'):
        assert (await client.post('/api/v1/product-updates/' + action, headers=headers, json={'version': 0})).status_code == 403


async def test_review_insert_index_and_local_match(client, monkeypatch, tmp_path):
    headers, _ = await admin(client, monkeypatch)
    id = await seed_source(client, headers)
    fake_extraction(monkeypatch)
    store = VectorStore(str(tmp_path / 'updates-index'), TinyEmbedding())
    monkeypatch.setattr(__import__('app.ingestion.service', fromlist=['vectors']), 'vectors', store)
    draft = await prepare(client, headers, id)
    assert draft['preview']['mode'] == 'insert'
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 0
    response = await approve(client, headers, draft)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'succeeded' and result['product_id']
    assert store.collection('product_knowledge').count() == 1
    assert (await approve(client, headers, draft)).json()['product_id'] == result['product_id']
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 1
        assert await db.scalar(select(func.count()).select_from(Price)) == 0
    local = await products.search(SearchInput(query='AirPods 5'), {'requested_models': ['AirPods 5']})
    assert local['items'][0]['id'] == result['product_id']
    assert local['local_sufficient']
    assert any(e['type'] == 'mysql_committed' and e['after']['status'] == 'active' for e in result['events'])


async def test_existing_product_fills_and_conflicts_require_selection(client, monkeypatch):
    headers, _ = await admin(client, monkeypatch)
    async with database.session() as db:
        db.add(Product(id='existing', category_code='headphone', brand='Apple', model='AirPods 5 USB C',
                       name='原有商品', specs={'battery_hours': 24}, summary='保留原简介', source='original',
                       source_url=URL, source_updated_at=now(), content_hash='old', status='active'))
        await db.commit()
    id = await seed_source(client, headers)
    fake_extraction(monkeypatch)
    async def indexed(row): pass
    monkeypatch.setattr(updates, 'index_product', indexed)
    draft = await prepare(client, headers, id)
    assert draft['preview']['existing_product']['id'] == 'existing'
    assert [x['field'] for x in draft['preview']['additions']] == ['specs.weight_g']
    assert [x['field'] for x in draft['preview']['conflicts']] == ['specs.battery_hours']
    assert (await approve(client, headers, draft)).status_code == 200
    async with database.session() as db:
        row = await db.get(Product, 'existing')
        assert row.specs == {'battery_hours': 24, 'weight_g': 5}
        assert row.summary == '保留原简介'
        assert await db.scalar(select(func.count()).select_from(Product)) == 1
    # 新版本网页记录指向同一正式商品，显式选择后才替换冲突字段。
    next_id = await seed_source(client, headers, content=TEXT + '新版本。')
    next_draft = await prepare(client, headers, next_id)
    assert (await approve(client, headers, next_draft, ['specs.battery_hours'])).status_code == 200
    async with database.session() as db:
        assert (await db.get(Product, 'existing')).specs['battery_hours'] == 30
        assert await db.scalar(select(func.count()).select_from(Product)) == 1


async def test_sql_saved_when_index_fails_and_retry_does_not_reimport(client, monkeypatch):
    headers, _ = await admin(client, monkeypatch)
    id = await seed_source(client, headers)
    fake_extraction(monkeypatch)
    async def broken(row): raise RuntimeError('secret provider detail')
    monkeypatch.setattr(updates, 'index_product', broken)
    draft = await prepare(client, headers, id)
    response = await approve(client, headers, draft)
    assert response.status_code == 200 and response.json()['status'] == 'index_pending'
    assert 'secret' not in response.text
    pending = response.json()
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 1
    async def recovered(row): assert row.id == pending['product_id']
    monkeypatch.setattr(updates, 'index_product', recovered)
    response = await client.post(f'/api/v1/product-updates/{id}/retry-index', headers=headers,
                                 json={'version': pending['version']})
    assert response.json()['status'] == 'succeeded'
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 1


async def test_unverified_edits_and_stale_reviews_are_rejected(client, monkeypatch):
    headers, _ = await admin(client, monkeypatch)
    id = await seed_source(client, headers)
    fake_extraction(monkeypatch)
    draft = await prepare(client, headers, id)
    changed = dict(draft['draft'])
    changed['specs'] = {'battery_hours': 999}
    body = {'version': draft['version'], 'product': changed, 'field_evidence': draft['field_evidence']}
    response = await client.patch(f'/api/v1/product-updates/{id}/draft', headers=headers, json=body)
    assert response.status_code == 422
    changed['specs'] = {'battery_hours': 30}
    body['product'] = changed
    response = await client.patch(f'/api/v1/product-updates/{id}/draft', headers=headers, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['version'] > draft['version']
    assert (await approve(client, headers, draft)).status_code == 409
    assert (await client.post(f'/api/v1/product-updates/{id}/approve', headers=headers,
        json={'version': response.json()['version'], 'target_hash': '0' * 64})).status_code == 409


async def test_reject_and_restart_recovery_are_durable(client, monkeypatch):
    headers, _ = await admin(client, monkeypatch)
    id = await seed_source(client, headers)
    response = await client.post(f'/api/v1/product-updates/{id}/reject', headers=headers,
                                 json={'version': 0, 'note': '不是具体产品页'})
    assert response.json()['status'] == 'rejected'
    assert (await client.post('/api/v1/product-updates/sync', headers=headers)).json()['added_count'] == 0
    async with database.session() as db:
        await db.execute(update(ProductUpdate).values(status='processing', version=3))
        await updates.recover_interrupted(db)
        await db.commit()
    restored = await updates.detail(id)
    assert restored['status'] == 'extract_failed' and restored['version'] == 4
    assert restored['error_code'] == 'PROCESS_RESTARTED'


async def test_extraction_failure_preserves_record_without_products(client, monkeypatch):
    headers, _ = await admin(client, monkeypatch)
    id = await seed_source(client, headers)
    async def broken(url): raise RuntimeError('secret key must be hidden')
    monkeypatch.setattr(updates, 'fetch_product_page', broken)
    response = await client.post(f'/api/v1/product-updates/{id}/prepare', headers=headers, json={'version': 0})
    assert response.status_code == 200 and response.json()['status'] == 'extract_failed'
    assert 'secret' not in response.text
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 0
        assert await db.scalar(select(func.count()).select_from(WebEvidence)) == 1


def test_official_source_gate():
    assert sources.official_source('https://www.sony.com.cn/products/test/?utm_source=tracking')[1] == 'Sony'
    for url in ('https://sony.com.cn.evil.example/product', 'https://127.0.0.1/',
                'https://user:secret@www.apple.com/', 'https://www.apple.com:8443/',
                'http://www.apple.com/', 'https://example.org/product'):
        with pytest.raises(Exception) as error:
            sources.official_source(url)
        assert error.value.code == 'OFFICIAL_SOURCE_REQUIRED'


def test_identity_normalizes_brand_prefix_but_keeps_configuration():
    base = {'category_code': 'phone', 'brand': 'Xiaomi', 'model': 'Xiaomi 17 Ultra 16GB+512GB'}
    assert updates.identity(base) == updates.identity({**base, 'model': '小米 17 Ultra 16GB 512GB'})
    assert updates.identity(base) != updates.identity({**base, 'model': '17 Ultra 12GB+256GB'})


@pytest.mark.parametrize('payload,valid', [({'results': [{'url': URL, 'raw_content': TEXT}]}, True),
    ({'results': [], 'failed_results': [{'url': URL, 'error': 'secret failure'}]}, False),
    ({'results': [{'url': 'https://evil.example/', 'raw_content': TEXT}]}, False)])
async def test_extract_checks_exact_result_and_redacts_errors(monkeypatch, payload, valid):
    original = httpx.AsyncClient
    def handle(request):
        assert request.url.path == '/extract'
        assert json.loads(request.content)['urls'] == [URL]
        return httpx.Response(200, json=payload)
    monkeypatch.setattr(settings, 'tavily_api_key', SecretStr('test-only-secret'))
    monkeypatch.setattr(sources.httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    if valid:
        assert (await sources.fetch_product_page(URL))['text'] == web.clean_text(TEXT, 15000)
    else:
        with pytest.raises(Exception) as error:
            await sources.fetch_product_page(URL)
        assert error.value.code == 'INSUFFICIENT_CONTENT' and 'secret' not in error.value.message
