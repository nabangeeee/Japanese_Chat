"""Offline API integrity tests: isolated SQLite and no provider/network calls."""
import asyncio
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import uuid

with patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "false"}), patch("dotenv.load_dotenv"):
    import database
    import main

from fastapi import BackgroundTasks, HTTPException


class APIIntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tracing = patch.dict(os.environ, {"LANGFUSE_TRACING_ENABLED": "false"})
        tracing.start()
        self.addCleanup(tracing.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(database, "DB_PATH", str(Path(self.tmp.name) / "test.db"))
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        database.init_db()
        self.provider = patch.object(main, "generate_text", side_effect=AssertionError("Unexpected provider call"))
        self.mock_provider = self.provider.start()
        self.addCleanup(self.provider.stop)
        self.repair = patch.object(main, "_schedule_autonomous_repair")
        self.mock_repair = self.repair.start()
        self.addCleanup(self.repair.stop)

    async def new_session(self, **kwargs):
        result = await main.api_create_session(main.CreateSessionRequest(**kwargs))
        return result["session"]["session_id"]

    async def test_roleplay_arguments_round_trip_and_independent_defaults(self):
        args = {"place": "東京", "preferences": {"drink": "お茶"}}
        session_id = await self.new_session(roleplay_id="cafe", roleplay_args=args)
        detail = await main.get_session_detail(session_id)
        self.assertEqual(detail["session"]["roleplay_args"], args)
        first, second = main.CreateSessionRequest(), main.CreateSessionRequest()
        first.roleplay_args["place"] = "大阪"
        self.assertEqual(second.roleplay_args, {})

    async def test_parallel_chat_returns_unique_stored_uuid_ids(self):
        session_id = await self.new_session()
        barrier = threading.Barrier(2, timeout=2)

        def generate(*args, **kwargs):
            barrier.wait()
            return "こんにちは。"

        self.mock_provider.side_effect = generate
        results = await asyncio.gather(*[
            main.chat(main.ChatRequest(message=text, api_key="test-key", session_id=session_id), BackgroundTasks())
            for text in ("おはよう", "こんばんは")
        ])
        stored = {m["id"]: m for m in database.get_session_messages(session_id)}
        self.assertEqual(len(stored), 4)
        ids = []
        for result, text in zip(results, ("おはよう", "こんばんは")):
            for field, role, content in (("message_id", "assistant", result["response"]), ("user_message_id", "user", text)):
                msg_id = result[field]
                self.assertEqual(str(uuid.UUID(msg_id)), msg_id)
                self.assertEqual(stored[msg_id]["role"], role)
                self.assertEqual(stored[msg_id]["content"], content)
                ids.append(msg_id)
        self.assertEqual(len(set(ids)), 4)

    async def test_missing_session_rejected_before_provider_or_tasks(self):
        tasks = BackgroundTasks()
        with self.assertRaises(HTTPException) as caught:
            await main.chat(main.ChatRequest(message="こんにちは", api_key="test-key", session_id="missing"), tasks)
        self.assertEqual(caught.exception.status_code, 404)
        self.mock_provider.assert_not_called()
        self.assertEqual(tasks.tasks, [])

    async def test_async_provider_routes_allow_parallel_requests(self):
        for route_name in ("multi_chat", "translate", "furigana"):
            with self.subTest(route=route_name):
                barrier = threading.Barrier(2, timeout=2)
                def generate(*args, **kwargs):
                    barrier.wait()
                    return "こんにちは。"
                self.mock_provider.side_effect = generate
                req = (main.ChatRequest(message="こんにちは", api_key="test-key")
                       if route_name == "multi_chat" else main.TranslateRequest(text="こんにちは", api_key="test-key"))
                route = getattr(main, route_name)
                results = await asyncio.gather(*[route(req, BackgroundTasks()) for _ in range(2)], return_exceptions=True)
                self.assertTrue(all(isinstance(result, dict) for result in results), results)

    async def test_invalid_feedback_is_422_without_scheduled_analysis(self):
        session_id = await self.new_session()
        other_id = await self.new_session()
        database.save_message("user-id", session_id, "user", "質問")
        database.save_message("assistant-id", session_id, "assistant", "返事")
        for message_id, target_session, rating in (
            ("missing", session_id, -1), ("user-id", session_id, -1),
            ("assistant-id", other_id, -1), ("assistant-id", session_id, 0),
        ):
            with self.subTest(message_id=message_id, session=target_session, rating=rating):
                tasks = BackgroundTasks()
                try:
                    await main.api_submit_feedback(main.FeedbackRequest(message_id=message_id, session_id=target_session, rating=rating, feedback_text="不自然", api_key="test-key"), tasks)
                except Exception as exc:
                    self.assertIsInstance(exc, HTTPException)
                    assert isinstance(exc, HTTPException)
                    self.assertEqual(exc.status_code, 422)
                else:
                    self.fail("Invalid feedback accepted")
                self.assertEqual(tasks.tasks, [])
        self.mock_provider.assert_not_called()

    async def test_feedback_without_session_schedules_resolved_session(self):
        session_id = await self.new_session()
        database.save_message("assistant-id", session_id, "assistant", "返事")
        tasks = BackgroundTasks()
        result = await main.api_submit_feedback(main.FeedbackRequest(message_id="assistant-id", rating=-1, feedback_text="不自然", api_key="test-key"), tasks)
        self.assertEqual(result["feedback"]["session_id"], session_id)
        self.assertEqual(tasks.tasks[0].args[2], session_id)

    async def test_feedback_analysis_requires_exact_assistant_in_session(self):
        session_id = await self.new_session()
        other_id = await self.new_session()
        database.save_message("user-id", session_id, "user", "質問")
        database.save_message("assistant-id", session_id, "assistant", "返事")
        for message_id, target_session in (("missing", session_id), ("id", session_id), ("user-id", session_id), ("assistant-id", other_id), ("assistant-id", "deleted-session")):
            with self.subTest(message_id=message_id, session=target_session):
                self.mock_provider.reset_mock()
                main._analyze_feedback_background("test-key", message_id, target_session, -1, "不自然")
                self.mock_provider.assert_not_called()

    async def test_feedback_analysis_uses_exact_target_not_latest(self):
        session_id = await self.new_session()
        database.save_message("user-id", session_id, "user", "元の質問")
        database.save_message("assistant-id", session_id, "assistant", "対象の返事")
        database.save_message("latest-id", session_id, "assistant", "別の返事")
        self.mock_provider.side_effect = None
        self.mock_provider.return_value = "RULE: 日本語で答える"
        main._analyze_feedback_background("test-key", "assistant-id", session_id, -1, "不自然")
        prompt = self.mock_provider.call_args.args[1]
        self.assertIn("対象の返事", prompt)
        self.assertNotIn("別の返事", prompt)

    async def test_session_deleted_during_generation_is_404_not_repair(self):
        session_id = await self.new_session()
        def generate(*args, **kwargs):
            database.delete_session(session_id)
            return "こんにちは。"
        self.mock_provider.side_effect = generate
        tasks = BackgroundTasks()
        with self.assertRaises(HTTPException) as caught:
            await main.chat(main.ChatRequest(message="こんにちは", api_key="test-key", session_id=session_id), tasks)
        self.assertEqual(caught.exception.status_code, 404)
        self.mock_repair.assert_not_called()
        self.assertEqual(tasks.tasks, [])
        self.assertEqual(database.get_session_messages(session_id), [])
