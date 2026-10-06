import unittest
from pathlib import Path
from unittest.mock import patch
import httpx
import scheduled_store as store

OWNER = '11111111-1111-4111-8111-111111111111'


class ScheduledStoreTests(unittest.TestCase):
    def run_reader(self, *, actual_owner=OWNER, row_owner=OWNER, login_status=200):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path == '/auth/v1/token':
                return httpx.Response(login_status, json={'access_token': 'private-token'})
            if request.url.path == '/auth/v1/user':
                return httpx.Response(200, json={'id': actual_owner})
            if request.url.path == '/auth/v1/logout':
                return httpx.Response(204)
            return httpx.Response(200, json=[{'user_id': row_owner, 'role':'user', 'content':'日本語'}])
        client = httpx.Client(base_url='https://test.supabase.co', transport=httpx.MockTransport(handler))
        with patch.object(store, 'config', return_value=('https://test.supabase.co', 'sb_publishable_test', 'me@example.com', 'password', OWNER)), patch.object(store.httpx, 'Client', return_value=client):
            with store.reader(Path('.')) as read:
                read('messages', columns='role,content', order='timestamp.desc', limit=80)
        return requests

    def test_owner_filter_and_local_logout(self):
        requests = self.run_reader()
        data = [r for r in requests if r.url.path.startswith('/rest/')]
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0].method, 'GET')
        self.assertEqual(data[0].url.params['user_id'], 'eq.' + OWNER)
        self.assertEqual(data[0].headers['Authorization'], 'Bearer private-token')
        self.assertEqual(requests[-1].url.params['scope'], 'local')

    def test_wrong_account_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'UID'):
            self.run_reader(actual_owner='another-user')

    def test_foreign_rows_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, '소유자'):
            self.run_reader(row_owner='another-user')

    def test_failed_login_is_sanitized(self):
        with self.assertRaisesRegex(RuntimeError, 'HTTP 400'):
            self.run_reader(login_status=400)

    def test_no_configuration_fails_closed(self):
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, '.env.scheduled'):
                store.config(Path(temp))

    def test_digest_and_metrics_use_cloud_reader(self):
        from morning_digest import recent_conversation_text
        from continuous_improvement import load_metrics
        with patch.object(store, 'reader') as reader:
            read = reader.return_value.__enter__.return_value
            read.return_value = [{'role':'assistant','content':'new'}, {'role':'user','content':'old'}]
            self.assertEqual(recent_conversation_text(Path('/missing')), 'user: old\nassistant: new')
            read.side_effect = [[{'content':'hello', 'quality_score':5, 'response_time_sec':9}], [{'rating':-1}]]
            metrics = load_metrics(Path('/missing'))
            self.assertEqual(metrics['sample_count'], 1)
            self.assertEqual(metrics['negative_feedback_rate'], 1)
            self.assertEqual(read.call_args_list[-2].kwargs['role'], 'eq.assistant')

    def test_observer_does_not_propose_from_missing_cloud_data(self):
        from continuous_improvement import observe
        with patch.object(store, 'reader', side_effect=RuntimeError('offline')), patch('continuous_improvement.create_proposal') as propose:
            with self.assertRaisesRegex(RuntimeError, 'offline'):
                observe(project_root=Path('/missing'))
            propose.assert_not_called()

    def test_digest_cache_is_scoped_to_owner(self):
        import tempfile
        import json
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from morning_digest import generate_digest
        with tempfile.TemporaryDirectory() as temp, patch.object(store, 'owner_id', return_value=OWNER):
            folder = Path(temp) / 'scratch' / 'digests' / OWNER
            folder.mkdir(parents=True)
            day = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
            (folder / (day + '.json')).write_text(json.dumps({'message':'owner digest'}))
            self.assertEqual(generate_digest(project_root=Path(temp)), 'owner digest')
