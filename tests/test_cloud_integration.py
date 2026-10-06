import os
import unittest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI, BackgroundTasks
from fastapi.testclient import TestClient
import cloud_store
from cloud_auth import SupabaseAuthMiddleware, auth_router
import database


class CloudIntegrationTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'DATABASE_BACKEND': 'supabase',
            'SUPABASE_URL': 'https://example.supabase.co', 'SUPABASE_PUBLISHABLE_KEY': 'sb_publishable_test'})
        env.start()
        self.addCleanup(env.stop)
        self.app = FastAPI()
        self.app.add_middleware(SupabaseAuthMiddleware)
        self.app.include_router(auth_router)
        self.seen = []

        @self.app.get('/api/records')
        async def records(tasks: BackgroundTasks):
            tasks.add_task(lambda: self.seen.append(cloud_store.owner()))
            return {'owner': cloud_store.owner()}

        self.client = TestClient(self.app)

    def test_missing_invalid_token_never_reaches_records(self):
        self.assertEqual(self.client.get('/api/records').status_code, 401)
        from fastapi import HTTPException
        with patch('cloud_auth.auth_call', new=AsyncMock(side_effect=HTTPException(401))):
            self.assertEqual(self.client.get('/api/records', headers={'Authorization':'Bearer fake'}).status_code, 401)
        self.assertEqual(self.seen, [])

    def test_user_identity_and_background_work_are_isolated(self):
        users = ['11111111-1111-4111-8111-111111111111', '22222222-2222-4222-8222-222222222222']
        with patch('cloud_auth.auth_call', new=AsyncMock(side_effect=[{'id':u} for u in users])):
            for user in users:
                result = self.client.get('/api/records', headers={'Authorization':'Bearer token'})
                self.assertEqual(result.json()['owner'], user)
                self.assertEqual(result.headers['cache-control'], 'no-store')
        self.assertEqual(self.seen, users)
        self.assertIsNone(cloud_store.identity.get())

    def test_cookie_refresh_and_cross_origin_rejection(self):
        from fastapi import HTTPException
        user = '11111111-1111-4111-8111-111111111111'
        self.client.cookies.set('nihongo_refresh_token', 'refresh')
        with patch('cloud_auth.auth_call', new=AsyncMock(side_effect=[
            {'access_token':'new','refresh_token':'rotated'}, {'id':user}])):
            result = self.client.get('/api/records')
        self.assertEqual(result.status_code, 200)
        self.assertIn('HttpOnly', result.headers['set-cookie'])
        self.assertEqual(self.client.post('/api/auth/logout', headers={'Origin':'https://attacker.example'}).status_code, 403)

    def test_database_dispatch_has_no_sqlite_fallback(self):
        with patch('cloud_store.get_all_sessions', return_value=[{'session_id':'cloud'}]) as cloud:
            self.assertEqual(database.get_all_sessions()[0]['session_id'], 'cloud')
            cloud.assert_called_once()
        with self.assertRaises(RuntimeError):
            database.get_db_connection()

    def test_rest_uses_user_token_and_owner_filter(self):
        import httpx
        marker = cloud_store.identity.set({'id':'owner-a','token':'user-token'})
        self.addCleanup(cloud_store.identity.reset, marker)
        with patch('cloud_store.httpx.request', return_value=httpx.Response(200, json=[])) as request:
            cloud_store.get_user_memories()
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer user-token')
        self.assertEqual(kwargs['params']['user_id'], 'eq.owner-a')

    def test_quota_denial_stops_inference(self):
        from fastapi import HTTPException
        from llm_provider import generate_text
        with patch('cloud_store.request', return_value=False), patch('llm_provider.OpenAI') as client:
            with self.assertRaises(HTTPException) as denied:
                generate_text('unused-key', 'hello')
            self.assertEqual(denied.exception.status_code, 429)
            client.return_value.__enter__.return_value.responses.create.assert_not_called()
