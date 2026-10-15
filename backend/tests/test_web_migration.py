from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from app.config import settings
from app.db.models import Base


def test_upgrade_existing_database_preserves_messages(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    engine = create_engine('sqlite:///' + str(path))
    Base.metadata.create_all(engine)
    with engine.begin() as db:
        db.execute(text('DROP TABLE product_updates'))
        db.execute(text('DROP TABLE web_search_cache'))
        db.execute(text('DROP TABLE web_evidence'))
        db.execute(text('ALTER TABLE chat_messages DROP COLUMN web_search'))
        db.execute(text("INSERT INTO chat_messages(id, created_at, session_id, role, content) VALUES ('old-message', CURRENT_TIMESTAMP, 'old-session', 'assistant', 'original answer')"))
        db.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)'))
        db.execute(text("INSERT INTO alembic_version VALUES ('0001')"))
    monkeypatch.setattr(settings, 'mysql_dsn', 'sqlite+aiosqlite:///' + str(path))
    command.upgrade(Config('alembic.ini'), 'head')
    command.upgrade(Config('alembic.ini'), 'head')
    assert {'web_evidence', 'web_search_cache'} <= set(inspect(engine).get_table_names())
    with engine.connect() as db:
        row = db.execute(text('SELECT content, web_search FROM chat_messages')).one()
        assert row == ('original answer', 0)
        assert db.execute(text('SELECT version_num FROM alembic_version')).scalar() == '0003'
    assert 'product_updates' in inspect(engine).get_table_names()
    engine.dispose()


def test_fresh_install_migration(tmp_path, monkeypatch):
    path = tmp_path / 'fresh.db'
    monkeypatch.setattr(settings, 'mysql_dsn', 'sqlite+aiosqlite:///' + str(path))
    command.upgrade(Config('alembic.ini'), 'head')
    engine = create_engine('sqlite:///' + str(path))
    assert 'web_search' in {column['name'] for column in inspect(engine).get_columns('chat_messages')}
    assert {'web_evidence', 'web_search_cache'} <= set(inspect(engine).get_table_names())
    assert 'product_updates' in inspect(engine).get_table_names()
    engine.dispose()
