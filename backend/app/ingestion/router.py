from typing import Annotated
from fastapi import APIRouter, Depends, Body, Query
from pydantic import BaseModel, HttpUrl, Field
from app.dependencies import admin_user
from app.products.schemas import ProductInput, PriceInput, ReviewInput
from app.ingestion.service import import_records, rebuild
from app.ingestion.crawler import preview
from app.ingestion.converter import convert
from app.ingestion import updates

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


class UpdateAction(BaseModel):
    version: int = Field(ge=0)


class PrepareUpdate(UpdateAction):
    url: HttpUrl | None = None


class EditUpdate(UpdateAction):
    product: ProductInput
    field_evidence: dict[str, Annotated[str, Field(max_length=3000)]] = Field(max_length=40)


class ApproveUpdate(UpdateAction):
    target_hash: str = Field(pattern=r'^[a-f0-9]{64}$')
    replace_fields: list[str] = Field(default_factory=list, max_length=40)


class RejectUpdate(UpdateAction):
    note: str = Field(default='', max_length=500)


@router.get('/product-updates')
async def update_list(status: str = '', q: str = Query(default='', max_length=100),
                      page: int = Query(default=1, ge=1), limit: int = Query(default=12, ge=1, le=100)):
    if status and status not in updates.STATUSES:
        from app.errors import AppError
        raise AppError(422, 'INVALID_STATUS', '记录状态无效')
    return await updates.list_records(status, q, page, limit)


@router.post('/product-updates/sync')
async def sync_updates():
    return await updates.sync_history()


@router.get('/product-updates/{id}')
async def update_detail(id: str):
    return await updates.detail(id)


@router.post('/product-updates/{id}/prepare')
async def prepare_update(id: str, data: PrepareUpdate, user=Depends(admin_user)):
    return await updates.prepare(id, data.version, str(data.url) if data.url else None, user.id)


@router.patch('/product-updates/{id}/draft')
async def edit_update(id: str, data: EditUpdate, user=Depends(admin_user)):
    return await updates.save_draft(id, data.version, data.product, data.field_evidence, user.id)


@router.post('/product-updates/{id}/approve')
async def approve_update(id: str, data: ApproveUpdate, user=Depends(admin_user)):
    return await updates.approve(id, data.version, data.target_hash, data.replace_fields, user.id)


@router.post('/product-updates/{id}/retry-index')
async def retry_update_index(id: str, data: UpdateAction):
    return await updates.retry_index(id, data.version)


@router.post('/product-updates/{id}/reject')
async def reject_update(id: str, data: RejectUpdate, user=Depends(admin_user)):
    return await updates.reject(id, data.version, data.note, user.id)
