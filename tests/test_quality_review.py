from __future__ import annotations

import unittest
from pathlib import Path
import re
from types import SimpleNamespace
from unittest.mock import patch

from main import parse_quality_judgement, review_response_quality_background


class QualityReviewTests(unittest.TestCase):
    def test_chat_schedules_quality_review(self) -> None:
        main_source = (
            Path(__file__).resolve().parents[1] / "main.py"
        ).read_text(encoding="utf-8")

        self.assertRegex(
            main_source,
            re.compile(
                r"bg_tasks\.add_task\(\s*review_response_quality_background",
                re.MULTILINE,
            ),
        )

    def test_parses_structured_judge_result(self) -> None:
        judgement = parse_quality_judgement(
            '```json\n{"score": 3.5, "reason": "질문에 답하지 않고 영어를 섞었습니다."}\n```'
        )

        self.assertEqual(judgement, (3.5, "질문에 답하지 않고 영어를 섞었습니다."))

    def test_parses_two_line_judge_result(self) -> None:
        self.assertEqual(
            parse_quality_judgement("SCORE: 8\nREASON: 자연스럽고 맥락에 맞습니다."),
            (8.0, "자연스럽고 맥락에 맞습니다."),
        )

    @patch("main.record_quality_incident")
    @patch("main.update_message_quality_score")
    @patch("main.genai.Client")
    def test_low_score_is_saved_as_observation_only(
        self, client_class, update_score, record_incident
    ) -> None:
        client_class.return_value.models.generate_content.return_value = SimpleNamespace(
            text='{"score": 2.0, "reason": "대화 맥락과 무관한 영어 답변"}'
        )

        review_response_quality_background(
            "api-key",
            "ast_1",
            "今日は何をしますか？",
            "I do not know.",
            "beginner",
            "free",
        )

        update_score.assert_called_once_with("ast_1", 2.0)
        record_incident.assert_called_once()
        self.assertEqual(record_incident.call_args.kwargs["score"], 2.0)
        self.assertIn(
            "대화 맥락과 무관한 영어 답변",
            record_incident.call_args.kwargs["reason"],
        )

    @patch("main.record_quality_incident")
    @patch("main.update_message_quality_score")
    @patch("main.genai.Client")
    def test_acceptable_score_does_not_create_quality_incident(
        self, client_class, update_score, record_incident
    ) -> None:
        client_class.return_value.models.generate_content.return_value = SimpleNamespace(
            text='{"score": 9.0, "reason": "자연스럽고 맥락에 맞음"}'
        )

        review_response_quality_background(
            "api-key",
            "ast_2",
            "元気ですか？",
            "はい、元気です！",
            "beginner",
            "free",
        )

        update_score.assert_called_once_with("ast_2", 9.0)
        record_incident.assert_not_called()


if __name__ == "__main__":
    unittest.main()
