"""指定型号的身份匹配与覆盖检查，不用向量近邻判断商品身份。"""
import re
import unicodedata

BRAND_ALIASES = {
    '索尼': 'sony', '小米': 'xiaomi', '红米': 'redmi', '苹果': 'apple',
    '华为': 'huawei', '荣耀': 'honor', '三星': 'samsung', '联想': 'lenovo',
    '戴尔': 'dell', '华硕': 'asus', '惠普': 'hp', '微软': 'microsoft',
}
BRANDS = tuple(BRAND_ALIASES.values()) + ('beats', 'oppo', 'vivo', 'realme', 'bose')


def canonical(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    for alias, brand in BRAND_ALIASES.items():
        text = text.replace(alias, brand)
    text = re.sub(r'耳机|手机|笔记本电脑|笔记本|平板电脑|平板|显示器|智能手表|头戴式|无线|降噪', '', text)
    return re.sub(r'[^a-z0-9\u4e00-\u9fff]', '', text)


def matches_model(item, requested):
    target = canonical(requested)
    if not target:
        return False
    identities = [canonical(item.get(field)) for field in ('model', 'name', 'brand')]
    brand = next((name for name in BRANDS if target.startswith(name)), None)
    if brand:
        # Beats 的业务 brand 可能记为 Apple，因此也核对商品名/型号。
        if not any(brand in value for value in identities):
            return False
        target = target[len(brand):]
    if not target:
        return True
    # 允许 Sony XM5 命中 Sony WH-1000XM5；不让 XM5 命中 XM50，
    # 也不把 iPhone 16 Pro Max / Studio Pro Plus 当作指定的基础型号。
    pattern = re.escape(target) + r'(?![a-z0-9])'
    return any(re.search(pattern, value) for value in identities)


def models_in_message(message):
    """对常见型号格式做兜底；主入口仍由需求提取器返回用户指定的原始型号。"""
    text = unicodedata.normalize('NFKC', message)
    patterns = [
        r'(?:索尼|Sony)\s*(?:WH\s*[- ]?\s*1000\s*[- ]?\s*XM\d+|WF\s*[- ]?\s*1000\s*[- ]?\s*XM\d+|XM\d+)',
        r'(?<![A-Za-z0-9])(?:WH|WF)\s*[- ]?\s*1000\s*[- ]?\s*XM\d+(?![A-Za-z0-9])',
        r'Beats\s+Studio\s+Pro(?:\s+Plus)?',
        r'AirPods\s*(?:Pro(?:\s*\d+)?|Max(?:\s*\d+)?|\d+)',
        r'iPhone\s*\d+(?:\s*Pro\s*Max|\s*Pro|\s*Plus|\s*mini)?',
        r'(?:小米|Xiaomi|Redmi|红米)\s*(?:Buds\s*\d+(?:\s*Pro)?|\d+(?:\s*Ultra|\s*Pro)?)',
        r'(?:Galaxy\s+)?Buds\s*\d+(?:\s*Pro)?',
    ]
    found = []
    for pattern in patterns:
        found.extend((match.start(), match.group().strip()) for match in re.finditer(pattern, text, re.I))
    result = []
    for _, value in sorted(found):
        if not any(canonical(value) == canonical(old) or canonical(value).endswith(canonical(old))
                   or canonical(old).endswith(canonical(value)) for old in result):
            result.append(value)
    return result[:5]


def local_coverage(items, state):
    requested = list(dict.fromkeys(state.get('requested_models') or []))
    missing = [name for name in requested if not any(matches_model(item, name) for item in items)]
    return {'local_sufficient': bool(items) and not missing,
            'requested_models': requested, 'missing_models': missing,
            'local_match_count': len(items)}
