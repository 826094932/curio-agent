from datetime import datetime, timezone
from decimal import Decimal
import numpy as np
import pytest
from pydantic import ValidationError
from app.db.chroma import VectorStore
from app.config import settings
from app.products.scoring import matches, score
from app.products.schemas import ProductInput, PriceInput, SearchInput
from app.products import service
from app.ingestion import service as ingestion
from app.db.mysql import database
from app.db.models import Product, Price
from sqlalchemy import select, func


class TinyEmbedding:
    def encode(self, texts, **kwargs):
        result = np.zeros((len(texts), 512))
        for index, text in enumerate(texts):
            result[index, 0] = 1
            result[index, 1] = 1 if '手机' in text else 0
        return result


def test_constraints_and_scoring():
    assert matches({'storage_gb': 256}, {'storage_gb_gte': 128})
    assert not matches({}, {'supports_nfc': True})
    with pytest.raises(ValueError):
        matches({}, {'invented': 1})
    items = [{'id': 'a', 'specs': {'battery_mah': 6000}, 'price': {'is_stale': False}}, {'id': 'b', 'specs': {}, 'price': {}}]
    result = score(items, 'phone', {'battery_mah': 3})
    assert result['items'][0]['id'] == 'a' and result['weights']['battery_mah'] == 1
    assert result['items'][1]['missing_fields'] == ['battery_mah']
    assert result == score(items[::-1], 'phone', {'battery_mah': 3})
    with pytest.raises(ValueError):
        score(items, 'phone', {'battery_mah': float('nan')})


def test_chroma_restart_idempotency_and_filter(tmp_path, monkeypatch):
    path = str(tmp_path / 'vectors')
    store = VectorStore(path, TinyEmbedding())
    store.upsert('product_knowledge', 'phone-1', '手机', {'product_id': 'phone-1', 'source_url': 'https://example.org', 'content_hash': 'one'})
    store.upsert('product_knowledge', 'phone-1', '手机', {'product_id': 'phone-1', 'source_url': 'https://example.org', 'content_hash': 'one'})
    restored = VectorStore(path, TinyEmbedding())
    assert restored.collection('product_knowledge').count() == 1
    assert restored.query('product_knowledge', '手机', {'product_id': 'phone-1'})[0]['evidence_id'] == 'phone-1'
    assert restored.query('product_knowledge', '手机', {'product_id': 'absent'}) == []


async def test_import_repeat_and_price_filter(client, tmp_path, monkeypatch):
    store = VectorStore(str(tmp_path / 'vectors'), TinyEmbedding())
    monkeypatch.setattr(ingestion, 'vectors', store)
    monkeypatch.setattr(service, 'vectors', store)
    captured = datetime(2025, 1, 1, tzinfo=timezone.utc)
    product = ProductInput(id='test-phone', category_code='phone', brand='Example', model='Phone', name='示例手机', summary='仅用于测试', specs={'storage_gb': 256}, source='test', source_url='https://example.org', source_updated_at=captured)
    assert (await ingestion.import_records('products', [product]))['status'] == 'succeeded'
    assert (await ingestion.import_records('products', [product]))['status'] == 'succeeded'
    price = PriceInput(product_id='test-phone', channel='test', final_price=Decimal('2999.00'), product_url='https://example.org', captured_at=captured)
    await ingestion.import_records('prices', [price])
    await ingestion.import_records('prices', [price])
    async with database.session() as db:
        assert await db.scalar(select(func.count()).select_from(Product)) == 1
        assert await db.scalar(select(func.count()).select_from(Price)) == 1
    assert (await service.search(SearchInput(query='手机', max_price=2500)))['items'] == []
    result = await service.search(SearchInput(query='手机', max_price=3000))
    assert result['items'][0]['price']['is_stale'] is True
    assert (await service.search(SearchInput(query='手机'), {'excluded_brands': ['Example']}))['items'] == []


def test_product_schema_rejects_bad_specs():
    with pytest.raises(ValidationError):
        ProductInput(id='x', category_code='phone', brand='a', model='b', name='c', summary='d', specs={'storage_gb': '256 GB'}, source='s', source_url='https://example.org', source_updated_at='2025-01-01T00:00:00Z')
