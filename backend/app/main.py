import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError
from app.config import settings
from app.db.mysql import database
from app.db.chroma import vectors
from app.db.models import AgentRun, SessionContext, now
from app.errors import AppError
from app.auth.router import router as auth_router
from app.chat.router import router as chat_router
from app.products.router import router as product_router
from app.ingestion.router import router as ingestion_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app):
    if database.engine:
        try:
            # 单实例约束：重启后将上次中断的运行标为失败，解除会话占用。
            async with database.session() as db:
                await db.execute(update(AgentRun).where(AgentRun.status == 'running').values(status='failed', error_code='PROCESS_RESTARTED', finished_at=now()))
                await db.execute(update(SessionContext).where(SessionContext.active_run_id.is_not(None)).values(active_run_id=None))
                await db.commit()
        except SQLAlchemyError:
            logger.warning('Database not ready; configure MYSQL_DSN and run alembic upgrade head.')
    yield
    if database.engine:
        await database.engine.dispose()


app = FastAPI(title='电子产品消费决策 Agent', version='0.1.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=['GET', 'POST', 'PATCH', 'DELETE'], allow_headers=['Authorization', 'Content-Type'])


@app.exception_handler(AppError)
async def app_error(request: Request, exc: AppError):
    return JSONResponse({'error': {'code': exc.code, 'message': exc.message}}, status_code=exc.status)


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    # 不向客户端输出 SQL、账号、连接串或底层驱动错误。
    logger.error('Database operation failed: %s', type(exc).__name__)
    return JSONResponse({'error': {'code': 'DATABASE_UNAVAILABLE', 'message': '数据库暂不可用，请检查连接与表结构'}}, status_code=503)


for router in (auth_router, chat_router, product_router, ingestion_router):
    app.include_router(router, prefix='/api/v1')


@app.get('/health')
async def health():
    return {'status': 'ok'}


@app.get('/ready')
async def ready():
    checks = {'database': False, 'chroma': False, 'deepseek_key': bool(settings.deepseek_api_key.get_secret_value()), 'jwt': len(settings.jwt_secret.get_secret_value()) >= 32}
    try:
        async with database.session() as db:
            await db.execute(text('SELECT id FROM users LIMIT 1'))
        checks['database'] = True
    except Exception:
        pass
    try:
        await asyncio.to_thread(vectors.client.heartbeat)
        checks['chroma'] = True
    except Exception:
        pass
    return JSONResponse({'status': 'ready' if all(checks.values()) else 'not_ready', 'checks': checks}, status_code=200 if all(checks.values()) else 503)
