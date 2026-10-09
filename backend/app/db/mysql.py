from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.errors import AppError


class Database:
    def __init__(self, url: str):
        self.engine = create_async_engine(url, pool_pre_ping=True) if url else None
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False) if self.engine else None

    def session(self):
        if self.sessions is None:
            raise AppError(503, 'DATABASE_NOT_CONFIGURED', '请在项目 .env 中配置 MYSQL_DSN，并执行数据库迁移')
        return self.sessions()


database = Database(settings.mysql_dsn)
