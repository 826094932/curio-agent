from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator
from app.products.scoring import SPEC_KEYS, normalize_constraints

CategoryCode = Literal['phone', 'laptop', 'headphone', 'monitor', 'tablet', 'smartwatch']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class ProductInput(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    category_code: CategoryCode
    brand: str = Field(min_length=1, max_length=64)
    model: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    summary: str = Field(min_length=1, max_length=10000)
    specs: dict[str, str | int | float | bool]
    source: str = Field(min_length=1, max_length=64)
    source_url: HttpUrl
    source_updated_at: datetime
    status: Literal['active', 'discontinued', 'draft'] = 'active'

    @field_validator('specs')
    @classmethod
    def validate_specs(cls, value):
        if set(value) - SPEC_KEYS:
            raise ValueError('存在未支持的规格字段: ' + ','.join(set(value) - SPEC_KEYS))
        for key, item in value.items():
            if key in {'supports_nfc', 'noise_cancelling'} and not isinstance(item, bool):
                raise ValueError(f'{key} 必须为布尔值')
            if key.endswith(('_gb', '_g', '_mah', '_w', '_hz', '_wh', '_hours', '_ms', '_pixels', '_nits', '_inches')):
                if isinstance(item, bool) or not isinstance(item, (int, float)) or item <= 0:
                    raise ValueError(f'{key} 必须为正数，单位使用字段名中的单位')
        return value


class PriceInput(StrictModel):
    product_id: str = Field(max_length=64)
    channel: str = Field(min_length=1, max_length=64)
    final_price: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    currency: Literal['CNY'] = 'CNY'
    in_stock: bool = True
    product_url: HttpUrl
    captured_at: datetime


class ReviewInput(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    product_id: str = Field(max_length=64)
    content: str = Field(min_length=2, max_length=10000)
    aspect: Literal['camera', 'battery', 'performance', 'screen', 'noise_cancelling', 'comfort', 'after_sales', 'general']
    sentiment: Literal['positive', 'neutral', 'negative']
    source: str = Field(min_length=1, max_length=64)
    source_url: HttpUrl
    reviewed_at: datetime


def utc(value: datetime):
    if value.tzinfo is None:
        raise ValueError('采集时间必须包含时区，例如 +08:00 或 Z')
    converted = value.astimezone(timezone.utc).replace(tzinfo=None)
    if converted > datetime.now(timezone.utc).replace(tzinfo=None):
        raise ValueError('采集时间不能在未来')
    return converted


class SearchInput(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    category: CategoryCode | None = None
    min_price: float | None = Field(default=None, ge=0)
    max_price: float | None = Field(default=None, ge=0)
    brands: list[str] = Field(default_factory=list, max_length=10)
    filters: dict[str, str | float | bool] = Field(default_factory=dict)
    top_k: int = Field(default=10, ge=1, le=30)

    @field_validator('filters')
    @classmethod
    def validate_filters(cls, value):
        return normalize_constraints(value)


class IdsInput(StrictModel):
    product_ids: list[str] = Field(min_length=1, max_length=20)


class ReviewSearch(IdsInput):
    aspects: list[str] = Field(default_factory=list, max_length=8)
    query: str = Field(default='优点 缺点 使用体验', max_length=300)
    top_k_per_product: int = Field(default=3, ge=1, le=5)


class CompareInput(IdsInput):
    category: CategoryCode
    weights: dict[str, float] = Field(default_factory=dict)


class PreferenceRead(StrictModel):
    category: CategoryCode | None = None


class PreferenceWrite(PreferenceRead):
    preferences: dict[str, str | int | float | bool | list[str]]
    consent: bool
