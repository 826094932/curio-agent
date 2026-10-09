from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from app.dependencies import current_user
from app.db.mysql import database
from app.db.models import Recommendation, RecommendationItem, Feedback
from app.products import service
from app.products.schemas import SearchInput, StrictModel, CategoryCode
from pydantic import Field
from app.errors import AppError

router = APIRouter(tags=['商品与推荐'], dependencies=[Depends(current_user)])


@router.get('/products/search')
async def search(query: str = Query(min_length=1, max_length=500), category: CategoryCode | None = None):
    return await service.search(SearchInput(query=query, category=category))


@router.get('/products/{id}')
async def product(id: str):
    result = await service.details([id])
    if not result:
        raise AppError(404, 'NOT_FOUND', '商品不存在')
    return result[0]


@router.get('/recommendations/{id}')
async def recommendation(id: str, user=Depends(current_user)):
    async with database.session() as db:
        item = await db.scalar(select(Recommendation).where(Recommendation.id == id, Recommendation.user_id == user.id))
        if not item:
            raise AppError(404, 'NOT_FOUND', '推荐不存在')
        products = (await db.scalars(select(RecommendationItem).where(RecommendationItem.recommendation_id == id).order_by(RecommendationItem.rank_no))).all()
        return {'id': id, 'answer': item.answer, 'sources': item.evidence, 'products': [p.snapshot for p in products]}


class FeedbackInput(StrictModel):
    recommendation_id: str
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default='', max_length=1000)


@router.post('/feedback', status_code=201)
async def feedback(data: FeedbackInput, user=Depends(current_user)):
    await recommendation(data.recommendation_id, user)
    async with database.session() as db:
        row = Feedback(user_id=user.id, **data.model_dump())
        db.add(row)
        await db.commit()
        return {'id': row.id}
