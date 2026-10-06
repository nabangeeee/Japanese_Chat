import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
import main


class FeedbackMemoryTests(unittest.TestCase):
    def test_notebook_hides_internal_rules_and_empty_values(self):
        import asyncio
        facts = [dict(fact_key='disliked_pattern_1', fact_value='None'),
                 dict(fact_key='disliked_pattern_2', fact_value='Speak simply'),
                 dict(fact_key='hobby', fact_value='reading'),
                 dict(fact_key=None, fact_value='null')]
        with patch.object(main, 'get_all_user_facts', return_value=facts), patch.object(main, 'get_all_sessions', return_value=[]):
            result = asyncio.run(main.api_list_facts())
        self.assertEqual(result['facts'], [facts[2]])

    def test_empty_feedback_is_not_used_in_prompt(self):
        with patch.object(main, 'get_all_user_facts', return_value=[dict(fact_key='disliked_pattern_1', fact_value='None')]), patch.object(main, 'retrieve_memories', return_value=[]):
            prompt = main.get_system_prompt('Yuki', 'beginner', 'free')
        self.assertNotIn('[Feedback-Based Refinement Rules]', prompt)

    def test_prompt_uses_two_newest_distinct_feedback_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(database, "DB_PATH", str(Path(temp_dir) / "test.db")):
                database.init_db()
                with database.get_db_connection() as conn:
                    conn.executemany(
                        "INSERT INTO user_facts (fact_key, fact_value, updated_at) VALUES (?, ?, ?)",
                        [
                            ("disliked_pattern_old", "old-rule", "2026-09-01"),
                            ("disliked_pattern_middle", "middle-rule", "2026-09-02"),
                            ("disliked_pattern_new", "new-rule", "2026-09-03"),
                            ("disliked_pattern_duplicate", "new-rule", "2026-09-04"),
                        ],
                    )
                prompt = main.get_system_prompt("ユキ", "beginner", "free")

        rules = prompt.split("[Feedback-Based Refinement Rules]", 1)[1]
        self.assertIn("- new-rule\n- middle-rule", rules)
        self.assertNotIn("old-rule", rules)

    def test_session_profile_does_not_reintroduce_outdated_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(database, "DB_PATH", str(Path(temp_dir) / "test.db")):
                database.init_db()
                database.create_session("session", "Test", "ユキ", "beginner", "free")
                database.save_session_summary("session", "Previous conversation summary")
                with database.get_db_connection() as conn:
                    conn.executemany(
                        "INSERT INTO user_facts (fact_key, fact_value, updated_at) VALUES (?, ?, ?)",
                        [
                            ("hobby", "reading", "2026-09-01"),
                            ("disliked_pattern_old", "old-rule", "2026-09-01"),
                            ("disliked_pattern_middle", "middle-rule", "2026-09-02"),
                            ("disliked_pattern_new", "new-rule", "2026-09-03"),
                        ],
                    )
                prompt = main.get_system_prompt("ユキ", "beginner", "free", session_id="session")

        self.assertIn("hobby=reading", prompt)
        self.assertIn("Previous conversation summary", prompt)
        self.assertNotIn("old-rule", prompt)
        self.assertNotIn("disliked_pattern_", prompt)
        self.assertEqual(prompt.count("new-rule"), 1)
        self.assertEqual(prompt.count("middle-rule"), 1)
