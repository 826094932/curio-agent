from typing import Annotated, Literal
from pydantic import Field, field_validator
from app.products.schemas import StrictModel, CategoryCode
from app.products.scoring import normalize_constraints


class ChatInput(StrictModel):
    session_id: str = Field(min_length=1, max_length=64)
    request_id: str = Field(pattern=r'^[A-Za-z0-9_-]{8,64}$')
    message: str = Field(min_length=1, max_length=4000)
    save_preference: bool = False
    web_search: bool = False


class SessionPatch(StrictModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    status: Literal['active', 'archived'] | None = None


class Requirements(StrictModel):
    category: CategoryCode | None = None
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    use_cases: list[str] = Field(default_factory=list, max_length=10)
    hard_constraints: dict[str, str | float | bool] = Field(default_factory=dict)
    excluded_brands: list[str] = Field(default_factory=list, max_length=10)
    preference_weights: dict[str, float] = Field(default_factory=dict)
    requested_models: list[Annotated[str, Field(min_length=1, max_length=128)]] = Field(
        default_factory=list, max_length=5,
        description='用户明确指定的商品型号或系列原称谓；对比时逐项列出；一般品类推荐填空列表，不臆测补全型号')

    @field_validator('hard_constraints')
    @classmethod
    def validate_hard_constraints(cls, value):
        return normalize_constraints(value)
