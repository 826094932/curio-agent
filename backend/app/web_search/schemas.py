from pydantic import Field
from app.products.schemas import StrictModel


class WebSearchInput(StrictModel):
    query: str = Field(min_length=2, max_length=500, description='商品型号或购买需求，不包含个人身份信息')

