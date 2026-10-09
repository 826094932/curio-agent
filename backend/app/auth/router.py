from fastapi import APIRouter, Depends, Request, Response
from app.auth import service
from app.auth.schemas import LoginInput, RegisterInput
from app.dependencies import current_user, check_origin
from app.config import settings

router = APIRouter(tags=['身份认证'])


def tokens(response, result):
    access, refresh = result
    response.set_cookie('refresh_token', refresh, httponly=True, secure=settings.cookie_secure, samesite='lax', max_age=604800, path='/api/v1/auth')
    return {'access_token': access, 'token_type': 'bearer'}


def guard(request):
    check_origin(request)
    service.rate_limit(request.client.host if request.client else 'unknown')


@router.post('/auth/register', status_code=201)
async def register(data: RegisterInput, request: Request):
    guard(request)
    return await service.register(data)


@router.post('/auth/login')
async def login(data: LoginInput, request: Request, response: Response):
    guard(request)
    return tokens(response, await service.login(data))


@router.post('/auth/refresh')
async def refresh(request: Request, response: Response):
    guard(request)
    return tokens(response, await service.rotate(request.cookies.get('refresh_token')))


@router.post('/auth/logout')
async def logout(request: Request, response: Response):
    check_origin(request)
    await service.logout(request.cookies.get('refresh_token'))
    response.delete_cookie('refresh_token', path='/api/v1/auth')
    return {'ok': True}


@router.get('/users/me')
async def me(user=Depends(current_user)):
    return {'id': user.id, 'email': user.email, 'nickname': user.nickname, 'is_admin': user.email in settings.admin_emails}
