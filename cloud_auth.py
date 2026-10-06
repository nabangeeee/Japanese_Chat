"""Same-origin Auth gateway; credentials/tokens never enter application storage."""
from uuid import UUID
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
import cloud_store as store

auth_router = APIRouter(prefix='/api/auth')


async def auth_call(path, *, token=None, data=None):
    url, key = store.settings()
    headers = {'apikey': key}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            result = await client.request('POST' if data is not None else 'GET',
                                          url + '/auth/v1/' + path, headers=headers, json=data)
    except httpx.HTTPError:
        raise HTTPException(503, '로그인 서버에 연결하지 못했습니다.') from None
    if result.is_error:
        raise HTTPException(401 if result.status_code in (400, 401, 403, 422) else 503,
                            '이메일·비밀번호 또는 로그인 상태를 확인해 주세요.')
    return result.json() if result.content else {}


def cookies(response, data, request):
    # Local HTTP development only; deployed HTTPS uses Secure cookies.
    secure = request.url.scheme == 'https' or request.url.hostname not in ('localhost', '127.0.0.1')
    for key, age in [('access_token', 3600), ('refresh_token', 2592000)]:
        response.set_cookie('nihongo_' + key, data[key], httponly=True, secure=secure,
                            samesite='strict', max_age=age, path='/api')


def same_origin(request):
    origin = request.headers.get('origin')
    return not origin or (urlsplit(origin).scheme, urlsplit(origin).netloc) == (request.url.scheme, request.url.netloc)


class SupabaseAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope['path'].startswith('/api/'):
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and not same_origin(request):
            return await JSONResponse({'detail': '허용되지 않은 요청입니다.'}, 403)(scope, receive, send)
        if scope['path'] in ('/api/auth/status', '/api/auth/login', '/api/auth/signup', '/api/auth/logout'):
            return await self.app(scope, receive, send)
        context = None
        refreshed = None
        try:
            bearer = request.headers.get('authorization', '')
            token = bearer[7:] if bearer.startswith('Bearer ') else request.cookies.get('nihongo_access_token')
            try:
                if not token:
                    raise HTTPException(401, '로그인이 필요합니다.')
                user = await auth_call('user', token=token)
            except HTTPException as exc:
                refresh = request.cookies.get('nihongo_refresh_token')
                if exc.status_code != 401 or bearer or not refresh:
                    raise
                refreshed = await auth_call('token?grant_type=refresh_token', data={'refresh_token': refresh})
                token = refreshed['access_token']
                user = await auth_call('user', token=token)
            verified_id = str(UUID(user['id']))
            expected_id = request.headers.get('x-nihongo-user')
            if expected_id and expected_id != verified_id:
                raise HTTPException(409, 'ACCOUNT_CHANGED')
            context = store.identity.set({'id': verified_id, 'token': token, 'email': user.get('email', '')})
        except HTTPException as exc:
            return await JSONResponse({'detail': exc.detail}, exc.status_code)(scope, receive, send)
        async def authenticated_send(message):
            if message['type'] == 'http.response.start':
                message['headers'] = list(message['headers']) + [(b'cache-control', b'no-store')]
                if refreshed:
                    holder = JSONResponse({})
                    cookies(holder, refreshed, request)
                    message['headers'].extend((k, v) for k, v in holder.raw_headers if k == b'set-cookie')
            await send(message)
        try:
            # Context remains active through response background tasks, and is
            # copied by Starlette when running synchronous work in a thread.
            await self.app(scope, receive, authenticated_send)
        finally:
            store.identity.reset(context)


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


@auth_router.get('/status')
async def status():
    return JSONResponse({'enabled': True}, headers={'Cache-Control': 'no-store'})


@auth_router.get('/me')
async def me():
    return {'user_id': store.owner(), 'email': store.identity.get().get('email', '')}


@auth_router.post('/login')
async def login(body: Credentials, request: Request):
    data = await auth_call('token?grant_type=password', data=body.model_dump())
    response = JSONResponse({'signed_in': True}, headers={'Cache-Control': 'no-store'})
    cookies(response, data, request)
    return response


@auth_router.post('/signup')
async def signup(body: Credentials, request: Request):
    data = await auth_call('signup', data=body.model_dump())
    response = JSONResponse({'signed_in': bool(data.get('access_token')),
                             'message': '메일함에서 가입 확인 메일을 확인해 주세요.'},
                            headers={'Cache-Control': 'no-store'})
    if data.get('access_token'):
        cookies(response, data, request)
    return response


@auth_router.post('/logout')
async def logout(request: Request):
    token = request.cookies.get('nihongo_access_token')
    if token:
        try:
            await auth_call('logout?scope=local', token=token, data={})
        except HTTPException:
            pass
    response = JSONResponse({'signed_out': True})
    for name in ('access_token', 'refresh_token'):
        response.delete_cookie('nihongo_' + name, path='/api')
    return response
