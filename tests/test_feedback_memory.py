import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cloud_store as database
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
        from cloud_fixture import cloud_fixture
        with cloud_fixture():
            for key, value in [('old','old-rule'), ('middle','middle-rule'), ('new','new-rule'), ('duplicate','new-rule')]:
                database.save_user_fact('disliked_pattern_' + key, value)
            prompt = main.get_system_prompt("ユキ", "beginner", "free")
        rules = prompt.split("[Feedback-Based Refinement Rules]", 1)[1]
        self.assertIn("- new-rule\n- middle-rule", rules)
        self.assertNotIn("old-rule", rules)

    def test_session_profile_does_not_reintroduce_outdated_rules(self):
        from cloud_fixture import cloud_fixture
        with cloud_fixture():
            database.create_session("session", "Test", "ユキ", "beginner", "free")
            database.save_session_summary("session", "Previous conversation summary")
            for key, value in [('hobby','reading'), ('disliked_pattern_old','old-rule'), ('disliked_pattern_middle','middle-rule'), ('disliked_pattern_new','new-rule')]:
                database.save_user_fact(key, value)
            prompt = main.get_system_prompt("ユキ", "beginner", "free", session_id="session")

        self.assertIn("hobby=reading", prompt)
        self.assertIn("Previous conversation summary", prompt)
        self.assertNotIn("old-rule", prompt)
        self.assertNotIn("disliked_pattern_", prompt)
        self.assertEqual(prompt.count("new-rule"), 1)
        self.assertEqual(prompt.count("middle-rule"), 1)
