"""Read-only Supabase access for personal scheduled jobs; no SQLite fallback."""
from contextlib import contextmanager
from pathlib import Path
import uuid

import httpx
from dotenv import dotenv_values


def config(root: Path):
    public = dotenv_values(root / '.env.supabase')
    private = dotenv_values(root / '.env.scheduled')
    url = (public.get('SUPABASE_URL') or '').rstrip('/')
    key = public.get('SUPABASE_PUBLISHABLE_KEY') or ''
    email = private.get('NIHONGO_SCHEDULED_EMAIL') or ''
    password = private.get('NIHONGO_SCHEDULED_PASSWORD') or ''
    try:
        owner = str(uuid.UUID(private.get('NIHONGO_SCHEDULED_USER_ID') or ''))
    except ValueError:
        owner = ''
    if not (url.startswith('https://') and key.startswith('sb_publishable_') and email and password and owner):
        raise RuntimeError('.env.scheduled에 본인 니혼고챗 이메일·비밀번호·User UID를 설정해 주세요.')
    return url, key, email, password, owner


def owner_id(root):
    return config(root)[4]


@contextmanager
def reader(root):
    url, key, email, password, owner = config(root)
    with httpx.Client(base_url=url, headers={'apikey': key}, timeout=20) as client:
        token = None
        try:
            login = client.post('/auth/v1/token?grant_type=password', json={'email': email, 'password': password})
            if login.status_code != 200:
                raise RuntimeError(f'예약 작업 로그인 실패 (HTTP {login.status_code})')
            token = login.json().get('access_token')
            if not token:
                raise RuntimeError('예약 작업 로그인 토큰 없음')
            client.headers['Authorization'] = 'Bearer ' + token
            me = client.get('/auth/v1/user')
            if me.status_code != 200 or me.json().get('id') != owner:
                raise RuntimeError('예약 작업 계정과 설정한 본인 UID가 일치하지 않습니다.')

            def read(table, *, columns, limit, order, **filters):
                response = client.get('/rest/v1/' + table, params={**filters,
                    'select': 'user_id,' + columns, 'user_id': 'eq.' + owner,
                    'limit': limit, 'order': order})
                if response.status_code != 200:
                    raise RuntimeError(f'예약 작업 DB 조회 실패 (HTTP {response.status_code})')
                rows = response.json()
                if not isinstance(rows, list) or any(row.get('user_id') != owner for row in rows):
                    raise RuntimeError('예약 작업 기록 소유자 불일치')
                return rows
            yield read
        except httpx.HTTPError:
            raise RuntimeError('예약 작업 Supabase 연결 실패') from None
        finally:
            if token:
                try:
                    client.post('/auth/v1/logout?scope=local')
                except httpx.HTTPError:
                    pass
