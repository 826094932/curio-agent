import math
import re

# 评分基于有来源的数值规格；不将缺失参数交给模型猜测。
# (最小值, 最大值, 越大越好)，固定范围使评分不随候选集合变化。
STRATEGIES = {
    'phone': {'battery_mah': (2000, 7000, True), 'charging_w': (10, 120, True), 'refresh_hz': (60, 144, True), 'storage_gb': (64, 1024, True), 'weight_g': (140, 250, False)},
    'laptop': {'ram_gb': (8, 64, True), 'storage_gb': (256, 2048, True), 'battery_wh': (30, 100, True), 'weight_g': (900, 3000, False), 'refresh_hz': (60, 240, True)},
    'headphone': {'battery_hours': (3, 60, True), 'weight_g': (4, 350, False), 'latency_ms': (20, 250, False)},
    'monitor': {'refresh_hz': (60, 240, True), 'resolution_pixels': (2073600, 8294400, True), 'brightness_nits': (200, 1000, True)},
    'tablet': {'battery_mah': (4000, 12000, True), 'storage_gb': (64, 1024, True), 'refresh_hz': (60, 144, True), 'weight_g': (300, 800, False)},
    'smartwatch': {'battery_hours': (18, 504, True), 'weight_g': (20, 80, False), 'brightness_nits': (500, 3000, True), 'storage_gb': (4, 64, True)},
}
COMMON_SPECS = {'supports_nfc', 'noise_cancelling', 'panel', 'cpu', 'gpu', 'chip', 'screen_inches', 'ram_gb', 'storage_gb', 'camera', 'color', 'os'}
SPEC_KEYS = COMMON_SPECS | set().union(*(set(x) for x in STRATEGIES.values()))


def normalize_constraints(constraints):
    normalized = {}
    for expression, expected in constraints.items():
        suffix = next((ending for ending in ('_gte', '_lte') if expression.endswith(ending)), '')
        key = expression[:-len(suffix)] if suffix else expression
        key = 'storage_gb' if key == 'storage' else key
        if key not in SPEC_KEYS:
            raise ValueError(f'不支持的筛选字段: {key}')
        if key == 'storage_gb':
            if isinstance(expected, str):
                value = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(GB|G|TB|T)?\s*', expected, re.I)
                if not value:
                    raise ValueError('存储容量须为 GB 数值，例如 256GB 或 1TB')
                expected = float(value[1]) * (1024 if value[2] and value[2].upper() in {'TB', 'T'} else 1)
            if isinstance(expected, bool) or not isinstance(expected, (int, float)) or not math.isfinite(expected) or expected <= 0:
                raise ValueError('存储容量须为正数，单位 GB')
        canonical = key + suffix
        if canonical in normalized and normalized[canonical] != expected:
            raise ValueError(f'筛选字段冲突: {canonical}')
        normalized[canonical] = expected
    return normalized


def matches(specs, constraints):
    for expression, expected in normalize_constraints(constraints).items():
        key = expression.removesuffix('_gte').removesuffix('_lte')
        actual = specs.get(key)
        if actual is None:
            return False
        try:
            if expression.endswith('_gte'):
                if isinstance(actual, bool) or float(actual) < float(expected):
                    return False
            elif expression.endswith('_lte'):
                if isinstance(actual, bool) or float(actual) > float(expected):
                    return False
            elif actual != expected:
                return False
        except (TypeError, ValueError):
            return False
    return True


def score(products, category, weights=None):
    strategy = STRATEGIES[category]
    weights = weights or {key: 1 for key in strategy}
    if set(weights) - set(strategy):
        raise ValueError('权重必须对应品类支持的数值规格: ' + ', '.join(strategy))
    if any(not math.isfinite(v) or v < 0 for v in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError('评分权重必须非负、有限且总和大于 0')
    total = sum(weights.values())
    normalized = {k: v / total for k, v in weights.items()}
    items = []
    for product in products:
        dimensions, missing = {}, []
        for key in normalized:
            value = product['specs'].get(key)
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                missing.append(key)
                dimensions[key] = 0
                continue
            low, high, positive = strategy[key]
            fraction = max(0, min(1, (value - low) / (high - low)))
            dimensions[key] = round(100 * (fraction if positive else 1 - fraction), 3)
        penalty = 5 if product.get('price', {}).get('is_stale', True) else 0
        items.append({**product, 'total_score': round(max(0, sum(dimensions[k] * normalized[k] for k in normalized) - penalty), 3), 'dimension_scores': dimensions, 'missing_fields': missing, 'stale_penalty': penalty})
    return {'items': sorted(items, key=lambda x: (-x['total_score'], x['id'])), 'weights': normalized,
            'method': '固定区间归一化；缺失项计零；过期或缺失价格扣 5 分。仅代表已采集规格，不代表整体产品质量。'}
