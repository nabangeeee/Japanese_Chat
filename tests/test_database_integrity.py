import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class DatabaseIntegrityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        override = patch.object(database, "DB_PATH", str(Path(temp.name) / "test.db"))
        override.start()
        self.addCleanup(override.stop)

    def session(self, session_id="session-1", **kwargs):
        return database.create_session(session_id, "Title", "Partner", "N5", "Travel", **kwargs)

    def test_roleplay_args_round_trip_and_safe_decode(self):
        database.init_db()
        args = {"place": "東京", "nested": {"choices": ["tea", "coffee"]}}
        created = self.session(roleplay_id="cafe", roleplay_args=args)
        self.assertEqual(created["roleplay_args"], args)
        self.assertEqual(database.get_session("session-1")["roleplay_args"], args)
        self.assertEqual(database.get_all_sessions()[0]["roleplay_args"], args)
        self.assertEqual(self.session("default")["roleplay_args"], {})
        with database.get_db_connection() as conn:
            stored = conn.execute("SELECT roleplay_args FROM sessions WHERE session_id = 'session-1'").fetchone()[0]
        self.assertEqual(json.loads(stored), args)
        for corrupt in ("not json", "[]", "null", '"string"', "42"):
            with self.subTest(corrupt=corrupt):
                with database.get_db_connection() as conn:
                    conn.execute("UPDATE sessions SET roleplay_args = ?", (corrupt,))
                self.assertEqual(database.get_session("session-1")["roleplay_args"], {})
                self.assertTrue(all(row["roleplay_args"] == {} for row in database.get_all_sessions()))

    def test_create_session_preserves_positional_compatibility(self):
        database.init_db()
        old = database.create_session("old", "Title", "Partner", "N5", "Travel", "cafe")
        self.assertEqual(old["roleplay_id"], "cafe")
        self.assertEqual(old["roleplay_args"], {})
        args = {"order": "お茶"}
        new = database.create_session("new", "Title", "Partner", "N5", "Travel", "cafe", args)
        self.assertEqual(database.get_session("new"), new)
        for index, invalid in enumerate((None, [], "not a dict", 42)):
            with self.subTest(invalid=invalid):
                created = self.session(f"invalid-{index}", roleplay_args=invalid)
                self.assertEqual(created["roleplay_args"], {})
                self.assertEqual(database.get_session(created["session_id"])["roleplay_args"], {})

    def test_feedback_rejects_legacy_message_without_session(self):
        database.init_db()
        # Older databases can contain orphan messages despite today's FK checks.
        with database.get_db_connection() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES ('orphan', 'missing', 'assistant', 'legacy')")
        for session_id in (None, "missing"):
            with self.subTest(session_id=session_id):
                with self.assertRaises(ValueError):
                    database.save_message_feedback("orphan", session_id, -1)
        with database.get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM message_feedbacks").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)

    def test_message_collision_preserves_message_score_and_feedback(self):
        database.init_db()
        self.session()
        self.session("other")
        database.save_message("msg", "session-1", "assistant", "original", translation="translation")
        database.update_message_quality_score("msg", 0.9)
        feedback = database.save_message_feedback("msg", "session-1", -1, "original feedback")
        original = database.get_session_messages("session-1")
        for target in ("session-1", "other"):
            with self.subTest(target=target):
                with self.assertRaises(sqlite3.IntegrityError):
                    database.save_message("msg", target, "user", "replacement")
                self.assertEqual(database.get_session_messages("session-1"), original)
                self.assertEqual(database.get_session_messages("other"), [])
                self.assertEqual(database.get_negative_feedbacks(), [feedback])

    def test_feedback_validates_target_without_writes_and_resolves_session(self):
        database.init_db()
        self.session()
        self.session("other")
        database.save_message("assistant", "session-1", "assistant", "hello")
        database.save_message("user", "session-1", "user", "hello")
        existing = database.save_message_feedback("assistant", "session-1", -1, "keep")
        for message_id, session_id, rating in (
            ("missing", None, 1), ("missing", "session-1", 1),
            ("user", None, 1), ("user", "session-1", 1),
            ("assistant", "other", 1), ("assistant", "missing", 1),
            ("assistant", "", 1), ("assistant", None, 0),
            ("assistant", None, 2),
        ):
            with self.subTest(message_id=message_id, session_id=session_id, rating=rating):
                with self.assertRaises(ValueError):
                    database.save_message_feedback(message_id, session_id, rating, "invalid")
                with database.get_db_connection() as conn:
                    self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM message_feedbacks")], [existing])
        updated = database.save_message_feedback("assistant", None, 1, "resolved")
        self.assertEqual(updated["session_id"], "session-1")
        self.assertEqual(updated["id"], existing["id"])
        with database.get_db_connection() as conn:
            self.assertEqual(dict(conn.execute("SELECT * FROM message_feedbacks").fetchone()), updated)

    def test_feedback_returns_id_when_session_deleted_just_after_commit(self):
        database.init_db()
        self.session()
        database.save_message("msg", "session-1", "assistant", "hello")
        original_commit = database.ClosingConnection.commit
        deleted = False

        def commit_then_delete(conn):
            nonlocal deleted
            original_commit(conn)
            if not deleted:
                deleted = True  # Guard the delete's own commit against recursion.
                self.assertTrue(database.delete_session("session-1"))

        with patch.object(database.ClosingConnection, "commit", commit_then_delete):
            feedback = database.save_message_feedback("msg", "session-1", 1)
        self.assertTrue(deleted)
        self.assertIsInstance(feedback["id"], int)
        self.assertGreater(feedback["id"], 0)
        self.assertEqual(feedback["message_id"], "msg")
        self.assertIsNone(database.get_session("session-1"))
        self.assertEqual(database.get_session_messages("session-1"), [])
        with database.get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM message_feedbacks").fetchone()[0], 0)

    def test_delete_session_removes_only_related_feedback(self):
        database.init_db()
        self.session()
        self.session("other")
        for msg, session in (("normal", "session-1"), ("null-session", "session-1"), ("wrong-session", "session-1"), ("keep", "other")):
            database.save_message(msg, session, "assistant", msg)
            database.save_message_feedback(msg, session, -1)
        with database.get_db_connection() as conn:
            conn.execute("UPDATE message_feedbacks SET session_id = NULL WHERE message_id = 'null-session'")
            conn.execute("UPDATE message_feedbacks SET session_id = 'other' WHERE message_id = 'wrong-session'")
            conn.execute("INSERT INTO message_feedbacks (message_id, session_id, rating) VALUES ('related-orphan', 'session-1', -1)")
            conn.execute("INSERT INTO message_feedbacks (message_id, session_id, rating) VALUES ('unrelated-orphan', NULL, -1)")
        database.init_db()
        self.assertEqual(len(database.get_negative_feedbacks()), 6)
        self.assertTrue(database.delete_session("session-1"))
        self.assertIsNone(database.get_session("session-1"))
        self.assertEqual(database.get_session_messages("session-1"), [])
        self.assertEqual({row["message_id"] for row in database.get_negative_feedbacks()}, {"keep", "unrelated-orphan"})
        self.assertFalse(database.delete_session("missing"))
        self.assertEqual(len(database.get_negative_feedbacks()), 2)

    def test_delete_session_feedback_is_rolled_back_on_failure(self):
        database.init_db()
        self.session()
        database.save_message("msg", "session-1", "assistant", "hello")
        feedback = database.save_message_feedback("msg", "session-1", -1)
        with database.get_db_connection() as conn:
            conn.execute("CREATE TRIGGER prevent_session_delete BEFORE DELETE ON sessions BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            database.delete_session("session-1")
        self.assertEqual(database.get_negative_feedbacks(), [feedback])
        self.assertEqual(len(database.get_session_messages("session-1")), 1)
        self.assertIsNotNone(database.get_session("session-1"))

    def test_legacy_migration_is_additive_and_repeatable(self):
        with database.get_db_connection() as conn:
            conn.execute("""CREATE TABLE sessions (
                session_id TEXT PRIMARY KEY, title TEXT NOT NULL, partner_name TEXT NOT NULL,
                difficulty TEXT NOT NULL, topic TEXT NOT NULL, roleplay_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("INSERT INTO sessions (session_id, title, partner_name, difficulty, topic) VALUES ('legacy', 'Old', 'Partner', 'N5', 'Travel')")
            conn.execute("""CREATE TABLE messages (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, translation TEXT, furigana TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("INSERT INTO messages (id, session_id, role, content) VALUES ('old-message', 'legacy', 'assistant', 'keep text')")
            conn.execute("""CREATE TABLE message_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT NOT NULL,
                session_id TEXT, rating INTEGER NOT NULL, feedback_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
            conn.execute("INSERT INTO message_feedbacks (message_id, session_id, rating, feedback_text) VALUES ('old-message', NULL, -1, 'keep feedback')")
            conn.execute("INSERT INTO message_feedbacks (message_id, session_id, rating) VALUES ('orphan', 'missing', -1)")
            old_session = dict(conn.execute("SELECT * FROM sessions").fetchone())
            old_message = dict(conn.execute("SELECT * FROM messages").fetchone())
            old_feedback = [dict(row) for row in conn.execute("SELECT * FROM message_feedbacks ORDER BY id")]
        for _ in range(2):
            database.init_db()
            migrated = database.get_session("legacy")
            self.assertEqual(migrated["roleplay_args"], {})
            self.assertEqual({key: migrated[key] for key in old_session}, old_session)
            message = database.get_session_messages("legacy")[0]
            self.assertEqual({key: message[key] for key in old_message}, old_message)
            self.assertIsNone(message["quality_score"])
            self.assertIsNone(message["response_time_sec"])
            with database.get_db_connection() as conn:
                self.assertEqual([dict(row) for row in conn.execute("SELECT * FROM message_feedbacks ORDER BY id")], old_feedback)
        self.assertEqual(database.get_all_sessions()[0]["title"], "Old")
        with database.get_db_connection() as conn:
            column = next(row for row in conn.execute("PRAGMA table_info(sessions)") if row["name"] == "roleplay_args")
            self.assertEqual(column["dflt_value"], "'{}'")


if __name__ == "__main__":
    unittest.main()