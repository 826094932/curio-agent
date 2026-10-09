from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
import jwt
from app.config import settings
from app.db.mysql import database
from app.db.models import User
from app.errors import AppError

bearer = HTTPBearer(auto_error=False)


async def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if not credentials:
        raise AppError(401, 'UNAUTHORIZED', '请先登录')
    try:
        claims = jwt.decode(credentials.credentials, settings.jwt_secret.get_secret_value(), algorithms=['HS256'], options={'require': ['exp', 'sub', 'iat', 'jti']})
    except jwt.PyJWTError:
        raise AppError(401, 'UNAUTHORIZED', '登录已过期')
    async with database.session() as db:
        user = await db.scalar(select(User).where(User.id == claims['sub'], User.status == 'active'))
    if not user:
        raise AppError(401, 'UNAUTHORIZED', '登录已失效')
    return user


async def admin_user(user=Depends(current_user)):
    if user.email not in [email.lower() for email in settings.admin_emails]:
        raise AppError(403, 'FORBIDDEN', '需要管理员权限')
    return user


def check_origin(request: Request):
    origin = request.headers.get('origin')
    if origin and origin not in settings.cors_origins:
        raise AppError(403, 'BAD_ORIGIN', '不允许的请求来源')
