"""Navigation remains responsive while Supabase is slow; no live API calls."""
import asyncio
import json
import threading
import unittest
from unittest.mock import patch

import httpx
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient

import cloud_auth
import cloud_store
import main
from cloud_fixture import cloud_fixture


class NavigationConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.enterContext(cloud_fixture())

    async def assert_storage_yields(self, operation, target, result):
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = threading.Event()
        owners = []

        def slow_store(*args, **kwargs):
            owners.append(cloud_store.owner())
            loop.call_soon_threadsafe(entered.set)
            if not release.wait(2):
                raise AssertionError('Storage blocked the event loop')
            return result

        with patch.object(main, target, side_effect=slow_store):
            pending = asyncio.create_task(operation())
            try:
                await asyncio.wait_for(entered.wait(), 1)
                # Another endpoint must finish while the first is waiting on DB.
                await asyncio.wait_for(main.api_list_mcp_prompts(), 1)
                self.assertFalse(pending.done())
            finally:
                release.set()
                await pending
        self.assertEqual(owners, ['test-owner'])

    async def test_navigation_storage_never_blocks_other_requests(self):
        cases = [
            (main.list_sessions, 'get_all_sessions', []),
            (lambda: main.api_create_session(main.CreateSessionRequest()), 'create_session', {}),
            (lambda: main.get_session_detail('session'), 'get_session', {'session_id': 'session'}),
            (lambda: main.get_session_detail('session'), 'get_session_messages', []),
            (lambda: main.api_delete_session('session'), 'delete_session', True),
            (main.api_list_memories, 'get_user_memories', []),
            (main.api_practice_memories, 'get_practice_memories', []),
            (lambda: main.api_review_memory(1, main.MemoryReviewRequest(remembered=True)),
             'record_memory_review', True),
            (main.api_list_facts, 'get_all_user_facts', []),
            (main.api_list_facts, 'get_session_summaries', {}),
            (lambda: main.api_submit_feedback(main.FeedbackRequest(message_id='msg', rating=1), BackgroundTasks()),
             'save_message_feedback', {}),
            (lambda: main.translate(main.TranslateRequest(text='こんにちは', api_key='unused', message_id='msg'), BackgroundTasks()),
             '_saved_detail', '안녕하세요'),
            (lambda: main.furigana(main.TranslateRequest(text='こんにちは', api_key='unused', message_id='msg'), BackgroundTasks()),
             '_saved_detail', 'こんにちは'),
        ]
        cloud_store.create_session('session', 'Test', 'Yuki', 'beginner', 'free')
        for operation, target, value in cases:
            with self.subTest(target=target):
                await self.assert_storage_yields(operation, target, value)

    async def test_notebook_batches_summaries_without_losing_order_or_owner(self):
        for i in range(205):
            sid = f'session-{i:03}'
            cloud_store.create_session(sid, sid, 'Yuki', 'beginner', 'free')
            if i % 2 == 0:
                cloud_store.save_session_summary(sid, f'Summary {i}')
        other = cloud_store.identity.set({'id': 'other-owner', 'token': 'other-token'})
        try:
            cloud_store.save_session_summary('session-000', 'Private summary')
        finally:
            cloud_store.identity.reset(other)
        expected = cloud_store.get_all_sessions()
        with patch.object(cloud_store, 'request', wraps=cloud_store.request) as requests:
            result = await main.api_list_facts()
        self.assertEqual([r['session_id'] for r in result['summaries']],
                         [s['session_id'] for s in expected if int(s['session_id'][-3:]) % 2 == 0])
        self.assertNotIn('Private summary', json.dumps(result))
        # Facts + sessions + three bounded batches, independent of 205 summaries.
        self.assertEqual(requests.call_count, 5)
        batches = [c.kwargs['params'] for c in requests.call_args_list if c.args[1] == 'session_summaries']
        self.assertEqual([b['limit'] for b in batches], [100, 100, 5])
        self.assertTrue(all(b['user_id'] == 'eq.test-owner' for b in batches))

    async def test_empty_notebook_does_not_fetch_summaries(self):
        with patch.object(cloud_store, 'request', wraps=cloud_store.request) as requests:
            self.assertEqual(await main.api_list_facts(), {'facts': [], 'summaries': []})
        self.assertEqual(requests.call_count, 2)


class SharedTransportTests(unittest.TestCase):
    def test_lifespan_reuses_transports_and_keeps_account_headers_separate(self):
        users = {'first': '11111111-1111-4111-8111-111111111111',
                 'second': '22222222-2222-4222-8222-222222222222'}
        auth_seen, db_seen = [], []

        def authenticate(request):
            token = request.headers['authorization'].split()[1]
            auth_seen.append(token)
            return httpx.Response(200, json={'id': users[token]})

        def storage(request):
            token = request.headers['authorization'].split()[1]
            db_seen.append((token, request.url.params['user_id']))
            return httpx.Response(200, json=[])

        sync_client = httpx.Client(transport=httpx.MockTransport(storage))
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(authenticate))
        # Build TestClient before patching HTTPX's client factories.
        browser = TestClient(main.app)
        with patch.object(cloud_store, 'settings', return_value=('https://example.supabase.co', 'sb_publishable_test')), \
             patch.object(main.httpx, 'Client', return_value=sync_client) as sync_factory, \
             patch.object(main.httpx, 'AsyncClient', return_value=async_client) as async_factory, \
             patch.object(cloud_store.httpx, 'request', side_effect=AssertionError('Unpooled storage request')):
            with browser:
                for token in ('first', 'second', 'first'):
                    response = browser.get('/api/sessions', headers={'Authorization': 'Bearer ' + token})
                    self.assertEqual(response.status_code, 200)
                self.assertFalse(sync_client.is_closed)
                self.assertFalse(async_client.is_closed)
            sync_factory.assert_called_once()
            async_factory.assert_called_once()
        self.assertEqual(auth_seen, ['first', 'second', 'first'])
        self.assertEqual(db_seen, [(t, 'eq.' + users[t]) for t in auth_seen])
        self.assertTrue(sync_client.is_closed)
        self.assertTrue(async_client.is_closed)
        self.assertIsNone(cloud_store.identity.get())

    def test_auth_without_lifespan_closes_its_temporary_client(self):
        client = httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'id': 'user'})))
        with patch.object(cloud_store, 'settings', return_value=('https://example.supabase.co', 'sb_publishable_test')), \
             patch.object(cloud_auth.httpx, 'AsyncClient', return_value=client):
            self.assertEqual(asyncio.run(cloud_auth.auth_call('user', token='token')), {'id': 'user'})
        self.assertTrue(client.is_closed)
