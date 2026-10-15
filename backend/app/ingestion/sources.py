"""品牌官网识别与公开产品页内容提取。"""
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from app.config import settings
from app.errors import AppError
from app.web_search.service import normalize_url, clean_text

BRAND_DOMAINS = {
    'apple.com.cn': 'Apple', 'apple.com': 'Apple', 'mi.com': 'Xiaomi',
    'sony.com.cn': 'Sony', 'sony.cn': 'Sony', 'sony.com': 'Sony',
    'beatsbydre.com': 'Beats', 'huawei.com': 'Huawei', 'honor.com': 'Honor',
    'samsung.com': 'Samsung', 'oppo.com': 'OPPO', 'vivo.com': 'vivo',
    'lenovo.com.cn': 'Lenovo', 'lenovo.com': 'Lenovo', 'dell.com': 'Dell',
    'asus.com': 'ASUS', 'hp.com': 'HP', 'bose.com': 'Bose', 'bose.cn': 'Bose',
}


def official_source(value):
    url = normalize_url(value)
    try:
        parsed = urlsplit(url or '')
        if parsed.scheme != 'https' or parsed.port not in (None, 443):
            raise ValueError()
    except ValueError:
        raise AppError(422, 'OFFICIAL_SOURCE_REQUIRED', '请填写受支持品牌的 HTTPS 官网产品页')
    host = parsed.hostname or ''
    brand = next((brand for domain, brand in BRAND_DOMAINS.items()
                  if host == domain or host.endswith('.' + domain)), None)
    if not brand:
        raise AppError(422, 'OFFICIAL_SOURCE_REQUIRED', '这条资料可保留为线索；入库前请换成受支持品牌的官网产品页')
    return url, brand


async def fetch_product_page(value):
    url, brand = official_source(value)
    key = settings.tavily_api_key.get_secret_value()
    if not key:
        raise AppError(503, 'WEB_SEARCH_NOT_CONFIGURED', '请先配置本地 TAVILY_API_KEY')
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post('https://api.tavily.com/extract',
                headers={'Authorization': f'Bearer {key}'},
                json={'urls': [url], 'extract_depth': 'basic', 'format': 'text',
                      'include_images': False, 'include_usage': True, 'timeout': 20})
        if response.status_code in (401, 403):
            raise AppError(503, 'WEB_SEARCH_AUTH_FAILED', '官网提取权限不可用，请检查配置')
        if response.status_code in (429, 432, 433):
            raise AppError(503, 'WEB_SEARCH_QUOTA', '官网提取额度不足或请求过于频繁')
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError()
        # HTTP 200 也可能只有 failed_results，不将失败正文当作商品资料。
        result = next((row for row in payload.get('results', [])
                       if isinstance(row, dict) and normalize_url(row.get('url')) == url), None)
        text = clean_text(result.get('raw_content'), 15000) if result else ''
        if len(text) < 100:
            raise AppError(422, 'INSUFFICIENT_CONTENT', '该页面未提取到足够正文，请换成具体产品或参数页')
        return {'source_url': url, 'title': '', 'text': text, 'json_ld': [],
                'brand': brand, 'captured_at': datetime.now(timezone.utc).isoformat()}
    except AppError:
        raise
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        raise AppError(502, 'PAGE_EXTRACTION_FAILED', '官网正文提取失败，请稍后重试') from exc
