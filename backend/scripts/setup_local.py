"""Configure a local MySQL database without placing credentials in source code."""
import asyncio
import getpass
import os
import secrets
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import dotenv_values, set_key


async def main():
    root = Path(__file__).resolve().parents[2]
    env = root / '.env'
    current = dotenv_values(env)
    user = os.environ.get('SETUP_MYSQL_USER') or input('MySQL user: ')
    password = os.environ.get('SETUP_MYSQL_PASSWORD') or getpass.getpass('MySQL password: ')
    server = URL.create('mysql+asyncmy', username=user, password=password, host='127.0.0.1', port=3306)
    engine = create_async_engine(server)
    try:
        async with engine.begin() as connection:
            await connection.execute(text('CREATE DATABASE IF NOT EXISTS product_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
    finally:
        await engine.dispose()
    set_key(env, 'MYSQL_DSN', server.set(database='product_agent').render_as_string(hide_password=False))
    if not current.get('JWT_SECRET'):
        set_key(env, 'JWT_SECRET', secrets.token_urlsafe(48))
    if not current.get('DEEPSEEK_MODEL'):
        set_key(env, 'DEEPSEEK_MODEL', 'deepseek-flash')
    print('MySQL product_agent ready. Local .env updated; credentials not printed.')


if __name__ == '__main__':
    asyncio.run(main())
