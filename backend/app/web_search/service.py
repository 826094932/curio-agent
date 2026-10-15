"""Tavily 搜索与独立网页证据缓存；仅由开启联网的工具路径调用。"""
import hashlib
import ipaddress
import math
import re
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db.models import WebEvidence, WebSearchCache, now
from app.db.mysql import database
from app.errors import AppError

OFFICIAL_DOMAINS = ('apple.com', 'apple.com.cn', 'beatsbydre.com', 'bose.com', 'bose.cn', 'sony.com', 'sony.com.cn', 'sony.cn', 'mi.com',
                    'huawei.com', 'vivo.com', 'oppo.com', 'samsung.com', 'lenovo.com',
                    'lenovo.com.cn', 'dell.com', 'asus.com', 'hp.com', 'honor.com')


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def normalize_url(value):
    """只保存公开 HTTP(S) 链接，删除跟踪参数，不访问结果链接。"""
    try:
        parsed = urlsplit(str(value))
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in ('http', 'https') or not host or parsed.username or parsed.password:
            return None
        if host == 'localhost' or host.endswith(('.local', '.internal')) or '.' not in host:
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            pass
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(k.lower() in {'api_key', 'apikey', 'token', 'access_token', 'key'} for k, _ in pairs):
            return None
        pairs = [(k, v) for k, v in pairs if not k.lower().startswith('utm_') and k.lower() not in {'gclid', 'fbclid'}]
        url = urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or '/', urlencode(sorted(pairs)), ''))
        return url if len(url) <= 1024 else None
    except (ValueError, TypeError):
        return None


def clean_text(value, limit):
    soup = BeautifulSoup(str(value or '')[:30000], 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    return re.sub(r'\s+', ' ', soup.get_text(' ', strip=True)).strip()[:limit]


def clean_results(payload):
    records, seen = [], set()
    for result in payload.get('results', [])[:10]:
        if not isinstance(result, dict):
            continue
        url = normalize_url(result.get('url', ''))
        title = clean_text(result.get('title'), 500)
        content = clean_text(result.get('content'), 4000)
        try:
            score = float(result.get('score', 0))
        except (ValueError, TypeError):
            continue
        if not url or url in seen or not title or len(content) < 40 or not math.isfinite(score) or score < 0.35:
            continue
        host = urlsplit(url).hostname
        seen.add(url)
        records.append({'url': url, 'title': title, 'content': content, 'score': min(score, 1.0),
                        'source_kind': 'official_domain' if any(host == d or host.endswith('.' + d) for d in OFFICIAL_DOMAINS) else 'web',
                        'published_at': clean_text(result.get('published_date'), 100) or None})
    return sorted(records, key=lambda row: (row['source_kind'] == 'official_domain', row['score']), reverse=True)[:5]


async def tavily_search(query):
    key = settings.tavily_api_key.get_secret_value()
    if not key:
        raise AppError(503, 'WEB_SEARCH_NOT_CONFIGURED', '联网搜索尚未配置 TAVILY_API_KEY')
    try:
        async with httpx.AsyncClient(timeout=settings.web_search_timeout_seconds, follow_redirects=False) as client:
            response = await client.post('https://api.tavily.com/search',
                headers={'Authorization': f'Bearer {key}'},
                json={'query': query, 'search_depth': 'basic', 'max_results': 5,
                      'include_answer': False, 'include_raw_content': False,
                      'include_usage': True, 'auto_parameters': False})
        if response.status_code in (401, 403):
            raise AppError(503, 'WEB_SEARCH_AUTH_FAILED', '联网搜索密钥无效或无权限，请检查配置')
        if response.status_code in (429, 432, 433):
            raise AppError(503, 'WEB_SEARCH_QUOTA', '联网搜索额度不足或请求过于频繁')
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
            raise ValueError('invalid search response')
        return payload
    except AppError:
        raise
    except (httpx.HTTPError, ValueError) as exc:
        # 不转发供应商异常正文、Authorization 或请求信息。
        raise AppError(503, 'WEB_SEARCH_UNAVAILABLE', '联网搜索暂不可用，请稍后重试') from exc


def as_source(row, cached=False, persisted=True):
    return {'id': 'web:' + row.id, 'url': row.url, 'title': row.title, 'text': row.content,
            'source_type': 'web', 'source_kind': row.source_kind, 'published_at': row.published_at,
            'fetched_at': row.fetched_at.isoformat() + 'Z', 'cached': cached,
            'persisted': persisted, 'score': row.relevance_score,
            'is_stale': now() - row.fetched_at > timedelta(hours=settings.web_search_cache_hours)}


async def cached_sources(user_id, query_hash, *, allow_stale=False):
    async with database.session() as db:
        cache = await db.scalar(select(WebSearchCache).where(WebSearchCache.user_id == user_id, WebSearchCache.query_hash == query_hash))
        if not cache or (not allow_stale and cache.expires_at <= now()):
            return []
        rows = (await db.scalars(select(WebEvidence).where(WebEvidence.user_id == user_id, WebEvidence.id.in_(cache.evidence_ids)))).all()
        by_id = {row.id: row for row in rows}
        return [as_source(by_id[id], cached=True) for id in cache.evidence_ids if id in by_id]


async def upsert(db, model, values, updates):
    dialect = db.bind.dialect.name
    if dialect == 'mysql':
        statement = mysql_insert(model).values(**values)
        statement = statement.on_duplicate_key_update(**updates)
    elif dialect == 'sqlite':
        statement = sqlite_insert(model).values(**values).on_conflict_do_update(index_elements=['id'], set_=updates)
    else:
        raise ValueError('unsupported database')
    await db.execute(statement)


async def search_and_save(user_id, query, state):
    # 同一查询在不同预算/硬约束下不能误用缓存；用户隔离由后端身份控制。
    import json
    scope = {k: state.get(k) for k in ('category', 'budget_min', 'budget_max', 'hard_constraints', 'excluded_brands', 'requested_models')}
    query = re.sub(r'\s+', ' ', query).strip()
    query_hash = digest(json.dumps([query.casefold(), scope], ensure_ascii=False, sort_keys=True))
    storage_available = True
    try:
        cached = await cached_sources(user_id, query_hash)
        if cached:
            return {'items': cached, 'status': 'cached', 'saved_count': 0, 'credits': 0, 'warning': None}
    except SQLAlchemyError:
        storage_available = False
    try:
        payload = await tavily_search(query)
    except AppError as exc:
        cached = []
        if storage_available:
            try:
                cached = await cached_sources(user_id, query_hash, allow_stale=True)
            except SQLAlchemyError:
                pass
        return {'items': cached, 'status': 'stale_cache' if cached else 'unavailable', 'saved_count': 0,
                'credits': 0, 'warning': exc.message, 'error': exc.code}
    records = clean_results(payload)
    fetched = now()
    rows = []
    for record in records:
        content_hash = digest(record['title'] + '\n' + record['content'])
        rows.append(WebEvidence(id=digest(user_id + '\n' + record['url'] + '\n' + content_hash),
                    user_id=user_id, url=record['url'], title=record['title'], content=record['content'],
                    content_hash=content_hash, relevance_score=record['score'], source_kind=record['source_kind'],
                    category=state.get('category'), published_at=record['published_at'], fetched_at=fetched))
    saved, warning, update_count = False, None, 0
    if rows and storage_available:
        try:
            async with database.session() as db:
                for row in rows:
                    values = {column.name: getattr(row, column.name) for column in WebEvidence.__table__.columns if column.name != 'created_at'}
                    await upsert(db, WebEvidence, values, {'fetched_at': fetched, 'relevance_score': row.relevance_score})
                cache_id = digest(user_id + ':' + query_hash)
                values = {'id': cache_id, 'user_id': user_id, 'query_hash': query_hash,
                          'evidence_ids': [row.id for row in rows], 'expires_at': fetched + timedelta(hours=settings.web_search_cache_hours)}
                await upsert(db, WebSearchCache, values, {'evidence_ids': values['evidence_ids'], 'expires_at': values['expires_at']})
                await db.commit()
            saved = True
            # 公开商品线索单独存队列；失败不回滚已保存证据，也不增加模型调用。
            try:
                from app.ingestion.updates import enqueue
                async with database.session() as db:
                    update_count = await enqueue(db, rows)
                    await db.commit()
            except SQLAlchemyError:
                warning = '网页证据已保存；商品更新记录未同步，可在管理员页面同步历史资料'
        except SQLAlchemyError:
            warning = '网页资料已获取，但数据库保存失败；本轮仍可参考来源'
    elif rows:
        warning = '网页资料已获取，但证据库暂不可用，请检查数据库迁移'
    usage = payload.get('usage') or {}
    credits = usage.get('credits') if isinstance(usage, dict) else None
    return {'items': [as_source(row, persisted=saved) for row in rows],
            'status': 'searched' if rows else 'empty', 'saved_count': len(rows) if saved else 0,
            'credits': credits, 'warning': warning, 'update_count': update_count}
