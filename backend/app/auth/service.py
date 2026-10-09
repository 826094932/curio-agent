import hashlib
import secrets
from datetime import timedelta
from collections import OrderedDict
from time import monotonic
import jwt
from pwdlib import PasswordHash
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from app.config import settings
from app.db.mysql import database
from app.db.models import User, AuthSession, uid, now
from app.errors import AppError

password_hasher = PasswordHash.recommended()
dummy_hash = password_hasher.hash('unregistered-user-password')
attempts = OrderedDict()


def rate_limit(key):
    current = monotonic()
    hits = [t for t in attempts.pop(key, []) if current - t < 60]
    if len(attempts) > 5000:
        attempts.popitem(last=False)
    attempts[key] = hits
    if len(hits) >= 10:
        raise AppError(429, 'RATE_LIMITED', '请求过于频繁，请稍后再试')
    hits.append(current)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def access_token(user_id):
    secret = settings.jwt_secret.get_secret_value()
    if len(secret) < 32:
        raise AppError(503, 'JWT_NOT_CONFIGURED', 'JWT_SECRET 至少需要 32 个字符')
    timestamp = now()
    return jwt.encode({'sub': user_id, 'jti': uid(), 'iat': timestamp, 'exp': timestamp + timedelta(minutes=15)}, secret, algorithm='HS256')


async def register(data):
    user = User(email=str(data.email).lower(), nickname=data.nickname, password_hash=password_hasher.hash(data.password))
    async with database.session() as db:
        db.add(user)
        try:
            await db.commit()
        except IntegrityError:
            raise AppError(409, 'EMAIL_EXISTS', '该邮箱无法注册')
    return {'id': user.id, 'email': user.email, 'nickname': user.nickname}


async def login(data):
    async with database.session() as db:
        user = await db.scalar(select(User).where(User.email == str(data.email).lower()))
        valid = password_hasher.verify(data.password, user.password_hash if user else dummy_hash)
        if not user or not valid or user.status != 'active':
            raise AppError(401, 'LOGIN_FAILED', '邮箱或密码错误')
        token = access_token(user.id)
        refresh = secrets.token_urlsafe(48)
        db.add(AuthSession(user_id=user.id, refresh_token_hash=digest(refresh), expires_at=now() + timedelta(days=7)))
        await db.commit()
        return token, refresh


async def rotate(refresh):
    if not refresh:
        raise AppError(401, 'UNAUTHORIZED', '登录已过期')
    async with database.session() as db:
        session = await db.scalar(select(AuthSession).where(AuthSession.refresh_token_hash == digest(refresh)))
        if not session or session.revoked_at or session.expires_at <= now():
            raise AppError(401, 'UNAUTHORIZED', '登录已过期')
        user = await db.get(User, session.user_id)
        if not user or user.status != 'active':
            raise AppError(401, 'UNAUTHORIZED', '账号不可用')
        # 条件更新防止两个刷新请求同时消费同一个 Refresh Token。
        result = await db.execute(update(AuthSession).where(AuthSession.id == session.id, AuthSession.revoked_at.is_(None)).values(revoked_at=now()))
        if result.rowcount != 1:
            raise AppError(401, 'UNAUTHORIZED', '登录凭证已经使用')
        token = access_token(user.id)
        replacement = secrets.token_urlsafe(48)
        db.add(AuthSession(user_id=user.id, refresh_token_hash=digest(replacement), expires_at=now() + timedelta(days=7)))
        await db.commit()
        return token, replacement


async def logout(refresh):
    if refresh:
        async with database.session() as db:
            await db.execute(update(AuthSession).where(AuthSession.refresh_token_hash == digest(refresh)).values(revoked_at=now()))
            await db.commit()
