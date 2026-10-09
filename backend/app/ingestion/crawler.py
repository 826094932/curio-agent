import asyncio
import ipaddress
import json
import re
import socket
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import httpx
from bs4 import BeautifulSoup
from app.config import settings, ROOT
from app.errors import AppError
from app.db.models import uid


NOISE = re.compile(r'(^|[-_ ])(global[-_ ]?)?(nav|footer|sidebar|breadcrumb|cookie|popup|modal|menu|toolbar|cart)([-_ ]|$)', re.I)
SKIP_LINES = {'购买', '立即购买', '进一步了解', '了解更多', '返回顶部', '登录', '注册'}


def product_json_ld(nodes):
    products = []

    def visit(node):
        if isinstance(node, list):
            for item in node:
                visit(item)
        elif isinstance(node, dict):
            types = node.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if any(kind in {'Product', 'ProductModel'} for kind in (types or [])):
                products.append(node)
            if '@graph' in node:
                visit(node['@graph'])

    visit(nodes)
    return products[:10]


def extract_page(content, url):
    soup = BeautifulSoup(content, 'html.parser')
    title = soup.title.get_text(' ', strip=True) if soup.title else ''
    structured = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            structured.append(json.loads(script.get_text()))
        except ValueError:
            pass
    structured = product_json_ld(structured)

    for element in soup.select('script, style, nav, footer, aside, form, noscript, svg, button, [role="navigation"], [role="banner"], [role="contentinfo"]'):
        element.decompose()
    for element in list(soup.find_all(True)):
        if element.parent is None:
            continue
        labels = ' '.join([element.get('id', ''), *element.get('class', [])])
        if NOISE.search(labels):
            element.decompose()

    scope = next((node for node in soup.select('main, [role="main"], article') if len(node.get_text(' ', strip=True)) >= 40), None)
    if scope is None:
        selectors = '[class*="spec"], [id*="spec"], [class*="product-detail"], [id*="product-detail"], [class*="product-content"], [id*="product-content"]'
        candidates = [node for node in soup.select(selectors) if len(node.get_text(' ', strip=True)) >= 40]
        scope = min(candidates, key=lambda node: len(node.get_text(' ', strip=True)), default=None)

    lines = []
    seen = set()
    if scope:
        for raw in scope.get_text('\n', strip=True).splitlines():
            line = re.sub(r'\s+', ' ', raw).strip()
            if len(line) < 2 or line in SKIP_LINES or line in seen:
                continue
            seen.add(line)
            lines.append(line)
    text = '\n'.join(lines)[:15000]
    warnings = []
    if len(text) < 40 and not structured:
        warnings.append('页面未提供足够的产品正文，可能依赖 JavaScript 渲染；请使用具体参数页或手动填写商品 JSON。')
    return {'source_url': url, 'title': title, 'text': text, 'json_ld': structured, 'warnings': warnings, 'captured_at': datetime.now(timezone.utc).isoformat(), 'status': 'draft'}


async def preview(url):
    parsed = urlsplit(url)
    host = parsed.hostname
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443) or host not in settings.crawler_domains:
        raise AppError(422, 'CRAWL_DOMAIN_DENIED', '仅允许 CRAWLER_DOMAINS 中配置的 HTTPS 官网域名')
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443)
    if not addresses or any(not ipaddress.ip_address(x[4][0]).is_global for x in addresses):
        raise AppError(422, 'PRIVATE_ADDRESS', '禁止抓取本地或内网地址')
    agent = 'ProductDecisionAgent/1.0'
    async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False, headers={'User-Agent': agent}) as client:
        robots_url = f'https://{host}/robots.txt'
        robot_response = await client.get(robots_url)
        if robot_response.status_code == 200:
            rules = RobotFileParser()
            rules.parse(robot_response.text.splitlines())
            if not rules.can_fetch(agent, url):
                raise AppError(403, 'ROBOTS_DENIED', '该页面不允许采集')
        elif robot_response.status_code != 404:
            raise AppError(502, 'ROBOTS_UNAVAILABLE', '无法确认 robots 规则，请稍后重试')
        await asyncio.sleep(1)
        async with client.stream('GET', url) as response:
            if response.status_code != 200:
                raise AppError(502, 'CRAWL_FAILED', '页面不可用或发生跳转，请填写最终官网链接')
            if 'text/html' not in response.headers.get('content-type', ''):
                raise AppError(422, 'NOT_HTML', '仅支持公开 HTML 产品页')
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > 2_000_000:
                    raise AppError(422, 'PAGE_TOO_LARGE', '页面超过 2 MB')
    result = extract_page(bytes(content), url)
    folder = ROOT / 'data' / 'raw'
    folder.mkdir(parents=True, exist_ok=True)
    id = uid()
    (folder / f'{id}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return {**result, 'draft_id': id}
