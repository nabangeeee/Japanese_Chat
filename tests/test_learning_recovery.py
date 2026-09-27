"""Recovery and learning persistence, using isolated SQLite and mocked inference."""
import asyncio
import os
from pathlib import Path
import tempfile
import threading
import sqlite3
import unittest
import uuid
from unittest.mock import patch

with patch.dict(os.environ, {'LANGFUSE_TRACING_ENABLED': 'false'}), patch('dotenv.load_dotenv'):
    import database
    import main
from fastapi import BackgroundTasks, HTTPException


class LearningRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        db_patch = patch.object(database, 'DB_PATH', str(Path(temp.name) / 'test.db'))
        db_patch.start()
        self.addCleanup(db_patch.stop)
        database.init_db()
        database.create_session('session', 'test', 'Yuki', 'beginner', 'free')
        provider = patch.object(main, 'generate_text', return_value='こんにちは。')
        self.generate = provider.start()
        self.addCleanup(provider.stop)
        repair = patch.object(main, '_schedule_autonomous_repair')
        repair.start()
        self.addCleanup(repair.stop)

    async def test_retry_after_lost_response_replays_without_inference(self):
        req = main.ChatRequest(message='こんにちは', api_key='test', session_id='session', request_id=uuid.uuid4())
        first = await main.chat(req, BackgroundTasks())
        tasks = BackgroundTasks()
        second = await main.chat(req, tasks)
        self.assertEqual(first, second)
        self.assertEqual(self.generate.call_count, 1)
        self.assertEqual(len(database.get_session_messages('session')), 2)
        self.assertEqual(tasks.tasks, [])
        req.message = 'changed'
        with self.assertRaises(HTTPException) as caught:
            await main.chat(req, BackgroundTasks())
        self.assertEqual(caught.exception.status_code, 409)

    async def test_provider_failure_saves_nothing_and_retry_succeeds(self):
        req = main.ChatRequest(message='こんにちは', api_key='test', session_id='session', request_id=uuid.uuid4())
        self.generate.side_effect = main.ProviderOutputError('temporary')
        with self.assertRaises(HTTPException):
            await main.chat(req, BackgroundTasks())
        self.assertEqual(database.get_session_messages('session'), [])
        self.generate.side_effect = None
        await main.chat(req, BackgroundTasks())
        self.assertEqual(len(database.get_session_messages('session')), 2)

    async def test_details_survive_reload_and_do_not_regenerate(self):
        database.save_message('reply', 'session', 'assistant', 'こんにちは。')
        for route, field, output in [(main.translate, 'translation', '안녕하세요.'), (main.furigana, 'furigana', 'こんにちは。')]:
            self.generate.return_value = output
            req = main.TranslateRequest(text='こんにちは。', api_key='test', message_id='reply')
            first = await route(req, BackgroundTasks())
            calls = self.generate.call_count
            req.api_key = ''
            second = await route(req, BackgroundTasks())
            self.assertEqual(first, second)
            self.assertEqual(self.generate.call_count, calls)
            self.assertEqual(database.get_session_messages('session')[0][field], first[field])
        req.text = 'different'
        with self.assertRaises(HTTPException) as caught:
            await main.translate(req, BackgroundTasks())
        self.assertEqual(caught.exception.status_code, 409)

    async def test_deleted_message_during_generation_is_404(self):
        database.save_message('reply', 'session', 'assistant', 'こんにちは。')
        def generate(*args, **kwargs):
            database.delete_session('session')
            return '안녕하세요.'
        self.generate.side_effect = generate
        with self.assertRaises(HTTPException) as caught:
            await main.translate(main.TranslateRequest(text='こんにちは。', api_key='test', message_id='reply'), BackgroundTasks())
        self.assertEqual(caught.exception.status_code, 404)

    async def test_practice_is_persisted_and_due_dates_differ(self):
        for number in range(4):
            database.save_user_memory('Grammar Error', str(number), 'corrected', 'reason')
        items = (await main.api_practice_memories())['memories']
        self.assertEqual(len(items), 3)
        for item, remembered in zip(items, (False, True, True)):
            await main.api_review_memory(item['id'], main.MemoryReviewRequest(remembered=remembered))
        self.assertEqual(len(database.get_practice_memories()), 1)
        reviewed = {item['id']: item for item in database.get_user_memories()}
        self.assertLess(reviewed[items[0]['id']]['next_review_at'], reviewed[items[1]['id']]['next_review_at'])
        database.init_db()  # Migrations are safe to rerun and retain practice progress.
        self.assertEqual(len(database.get_practice_memories()), 1)
        self.assertEqual(reviewed[items[0]['id']]['review_count'], 1)
        with self.assertRaises(HTTPException) as caught:
            await main.api_review_memory(999, main.MemoryReviewRequest(remembered=True))
        self.assertEqual(caught.exception.status_code, 404)

    async def test_chat_pair_rolls_back_if_second_insert_fails(self):
        database.save_message('assistant', 'session', 'assistant', 'existing')
        with self.assertRaises(sqlite3.IntegrityError):
            database.save_chat_turn('user', 'assistant', 'session', 'question', 'answer', 1)
        self.assertIsNone(database.get_message('user'))
        self.assertEqual(database.get_message('assistant')['content'], 'existing')


    async def test_simultaneous_retries_save_only_one_pair(self):
        req = main.ChatRequest(message='こんにちは', api_key='test', session_id='session', request_id=uuid.uuid4())
        barrier = threading.Barrier(2, timeout=3)
        def generate(*args, **kwargs):
            barrier.wait()
            return 'こんにちは。'
        self.generate.side_effect = generate
        tasks = [BackgroundTasks(), BackgroundTasks()]
        results = await asyncio.gather(*[main.chat(req, task) for task in tasks])
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(database.get_session_messages('session')), 2)
        self.assertEqual(sum(bool(task.tasks) for task in tasks), 1)

    async def test_legacy_notes_are_preserved_by_migration(self):
        with database.get_db_connection() as conn:
            conn.execute('DROP TABLE user_memories')
            conn.execute('CREATE TABLE user_memories (id INTEGER PRIMARY KEY, category TEXT, original_text TEXT, corrected_text TEXT, explanation TEXT, created_at TEXT)')
            conn.execute("INSERT INTO user_memories VALUES (5, 'Grammar Error', 'original', 'corrected', 'reason', '2026-01-01')")
        database.init_db()
        item = database.get_practice_memories()[0]
        self.assertEqual(item['id'], 5)
        self.assertEqual(item['corrected_text'], 'corrected')
        self.assertEqual(item['review_count'], 0)
        self.assertIsNone(item['next_review_at'])

    async def test_summary_skips_intermediate_turns(self):
        with patch.object(main, 'get_session_messages', return_value=[{'role': 'user', 'content': 'hello'}] * 8):
            main._update_session_summary_background('test', 'session')
        self.generate.assert_not_called()

    async def test_empty_translation_is_not_cached(self):
        database.save_message('reply', 'session', 'assistant', 'こんにちは。')
        self.generate.return_value = ''
        with self.assertRaises(HTTPException):
            await main.translate(main.TranslateRequest(text='こんにちは。', api_key='test', message_id='reply'), BackgroundTasks())
        self.assertIsNone(database.get_message('reply')['translation'])
