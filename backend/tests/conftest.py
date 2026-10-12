import pytest
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from httpx import AsyncClient, ASGITransport
from app.db.mysql import database
from app.db.models import Base
from app.config import settings
from app.main import app
from app.auth.service import attempts


@pytest.fixture
async def client(tmp_path, monkeypatch):
    engine = create_async_engine('sqlite+aiosqlite:///' + str(tmp_path / 'test.db'))
    monkeypatch.setattr(database, 'engine', engine)
    monkeypatch.setattr(database, 'sessions', async_sessionmaker(engine, expire_on_commit=False))
    monkeypatch.setattr(settings, 'jwt_secret', __import__('pydantic').SecretStr('a-unit-test-secret-that-is-long-enough'))
    attempts.clear()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncClient(transport=ASGITransport(app=app), base_url='http://test') as client:
        yield client
    await engine.dispose()


async def account(client, email='alice@example.com'):
    data = {'email': email, 'password': 'test-password-123'}
    response = await client.post('/api/v1/auth/register', json={**data, 'nickname': '测试用户'})
    assert response.status_code == 201, response.text
    response = await client.post('/api/v1/auth/login', json=data)
    assert response.status_code == 200, response.text
    return {'Authorization': 'Bearer ' + response.json()['access_token']}
