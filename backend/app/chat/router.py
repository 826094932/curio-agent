import asyncio
import contextlib
import json
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from app.dependencies import current_user
from app.db.mysql import database
from app.db.models import ChatSession, SessionContext, Message, AgentRun
from app.chat.schemas import ChatInput, SessionPatch
from app.chat.service import owned_session, prepare, execute
from app.errors import AppError
from app.chat.timing import RunTiming

router = APIRouter(tags=['会话与聊天'])


def session_json(row):
    return {'id': row.id, 'title': row.title, 'status': row.status, 'last_message_at': row.last_message_at.isoformat() + 'Z'}


@router.post('/sessions', status_code=201)
async def create_session(user=Depends(current_user)):
    async with database.session() as db:
        row = ChatSession(user_id=user.id)
        db.add(row)
        await db.flush()
        db.add(SessionContext(session_id=row.id))
        await db.commit()
        return session_json(row)


@router.get('/sessions')
async def sessions(user=Depends(current_user), offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    async with database.session() as db:
        rows = (await db.scalars(select(ChatSession).where(ChatSession.user_id == user.id, ChatSession.status != 'deleted').order_by(ChatSession.last_message_at.desc(), ChatSession.id.desc()).offset(offset).limit(limit))).all()
        return [session_json(row) for row in rows]


@router.get('/sessions/{id}/messages')
async def messages(id: str, before: str | None = None, limit: int = Query(50, ge=1, le=100), user=Depends(current_user)):
    async with database.session() as db:
        await owned_session(db, user.id, id)
        query = select(Message).where(Message.session_id == id)
        if before:
            query = query.where(Message.id < before)
        rows = (await db.scalars(query.order_by(Message.id.desc()).limit(limit + 1))).all()
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        timings = {}
        if rows:
            runs = (await db.scalars(select(AgentRun).where(AgentRun.user_id == user.id, AgentRun.session_id == id,
                    AgentRun.status == 'succeeded', AgentRun.finished_at >= rows[0].created_at,
                    AgentRun.created_at <= rows[-1].created_at))).all()
            for run in runs:
                if run.result.get('assistant_message_id') and run.result.get('timings'):
                    timings[run.result['assistant_message_id']] = run.result['timings']
        return {'items': [{'id': row.id, 'role': row.role, 'content': row.content, 'timings': timings.get(row.id)} for row in rows], 'next_cursor': rows[0].id if has_more else None}


@router.patch('/sessions/{id}')
async def patch_session(id: str, data: SessionPatch, user=Depends(current_user)):
    async with database.session() as db:
        row = await owned_session(db, user.id, id)
        context = await db.get(SessionContext, id)
        if context.active_run_id:
            raise AppError(409, 'SESSION_BUSY', '请等待回答结束')
        for key, value in data.model_dump(exclude_none=True).items():
            setattr(row, key, value)
        await db.commit()
        return session_json(row)


@router.delete('/sessions/{id}')
async def delete_session(id: str, user=Depends(current_user)):
    async with database.session() as db:
        row = await owned_session(db, user.id, id)
        context = await db.get(SessionContext, id)
        if context.active_run_id:
            raise AppError(409, 'SESSION_BUSY', '请等待回答结束')
        row.status = 'deleted'
        await db.commit()
        return {'ok': True}


@router.get('/runs/{request_id}')
async def run_status(request_id: str, user=Depends(current_user)):
    async with database.session() as db:
        run = await db.scalar(select(AgentRun).where(AgentRun.request_id == request_id, AgentRun.user_id == user.id))
        if not run:
            raise AppError(404, 'NOT_FOUND', '运行记录不存在')
        await owned_session(db, user.id, run.session_id)
        return {'request_id': run.request_id, 'status': run.status, 'result': run.result, 'error_code': run.error_code}


@router.post('/chat')
async def chat(data: ChatInput, user=Depends(current_user)):
    timing = RunTiming()
    with timing.span('prepare'):
        run, fresh = await prepare(user.id, data)
    if not fresh:
        return {'status': run.status, 'result': run.result, 'error_code': run.error_code}
    async def ignore(*args):
        pass
    return await execute(run, data, ignore, timing=timing)


@router.post('/chat/stream')
async def stream(data: ChatInput, request: Request, user=Depends(current_user)):
    timing = RunTiming()
    with timing.span('prepare'):
        run, fresh = await prepare(user.id, data)

    async def events():
        if not fresh:
            if run.status == 'succeeded':
                yield 'event: result\ndata: ' + json.dumps(run.result, ensure_ascii=False) + '\n\n'
                yield 'event: done\ndata: {}\n\n'
            else:
                yield 'event: error\ndata: ' + json.dumps({'code': run.error_code or 'RUNNING', 'message': '该请求已执行，请查询运行状态'}, ensure_ascii=False) + '\n\n'
            return
        queue = asyncio.Queue(maxsize=128)
        async def emit(event, content):
            await queue.put((event, content))
        async def producer():
            try:
                await execute(run, data, emit, timing=timing)
            except AppError as exc:
                await emit('error', {'code': exc.code, 'message': exc.message})
            finally:
                if asyncio.current_task().cancelling():
                    # 断线时消费者已退出，不能再等待一个满队列腾出位置。
                    with contextlib.suppress(asyncio.QueueFull):
                        queue.put_nowait(None)
                else:
                    await queue.put(None)
        task = asyncio.create_task(producer())
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except TimeoutError:
                    yield ': heartbeat\n\n'
                    continue
                if event is None:
                    break
                kind, content = event
                yield f'event: {kind}\ndata: {json.dumps(content, ensure_ascii=False)}\n\n'
        finally:
            if not task.done():
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
    return StreamingResponse(events(), media_type='text/event-stream', headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
