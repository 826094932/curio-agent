from typing import Annotated
from fastapi import APIRouter, Depends, Body
from pydantic import BaseModel, HttpUrl, Field
from app.dependencies import admin_user
from app.products.schemas import ProductInput, PriceInput, ReviewInput
from app.ingestion.service import import_records, rebuild
from app.ingestion.crawler import preview
from app.ingestion.converter import convert

router = APIRouter(tags=['数据管理'], dependencies=[Depends(admin_user)])


@router.post('/products/import')
async def products(records: Annotated[list[ProductInput], Body(min_length=1, max_length=100)]):
    return await import_records('products', records)


@router.post('/prices/import')
async def prices(records: Annotated[list[PriceInput], Body(min_length=1, max_length=500)]):
    return await import_records('prices', records)


@router.post('/reviews/import')
async def reviews(records: Annotated[list[ReviewInput], Body(min_length=1, max_length=100)]):
    return await import_records('reviews', records)


@router.post('/indexes/rebuild')
async def indexes():
    return await rebuild()


class CrawlInput(BaseModel):
    url: HttpUrl


@router.post('/sources/preview')
async def crawl(data: CrawlInput):
    return await preview(str(data.url))


class ConvertInput(BaseModel):
    draft_id: str = Field(min_length=26, max_length=26)


@router.post('/sources/convert')
async def convert_source(data: ConvertInput):
    return await convert(data.draft_id)
