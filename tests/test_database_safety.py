from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database


class DatabaseSafetyTests(unittest.TestCase):
    def test_feedback_is_upserted_once_and_wal_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            with patch.object(database, "DB_PATH", str(db_path)):
                database.init_db()
                first = database.save_message_feedback("msg-1", "session-1", -1, "bad")
                second = database.save_message_feedback("msg-1", "session-1", 1, "fixed")
                with database.get_db_connection() as conn:
                    count = conn.execute(
                        "SELECT COUNT(*) FROM message_feedbacks WHERE message_id = ?",
                        ("msg-1",),
                    ).fetchone()[0]
                    rating = conn.execute(
                        "SELECT rating FROM message_feedbacks WHERE message_id = ?",
                        ("msg-1",),
                    ).fetchone()[0]
                    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(count, 1)
        self.assertEqual(rating, 1)
        self.assertEqual(journal_mode.lower(), "wal")

    def test_feedback_rejects_invalid_rating(self) -> None:
        with self.assertRaises(ValueError):
            database.save_message_feedback("msg-1", None, 0)


if __name__ == "__main__":
    unittest.main()
