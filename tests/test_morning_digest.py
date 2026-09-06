from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from morning_digest import format_digest, generate_digest, parse_vocabulary_response


class MorningDigestTests(unittest.TestCase):
    def test_same_day_retry_reuses_persisted_payload_without_gemini(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            digest_dir = root / "scratch" / "digests"
            digest_dir.mkdir(parents=True)
            day = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
            (digest_dir / f"{day}.json").write_text(
                json.dumps({"message": "same payload", "items": []}), encoding="utf-8"
            )
            with patch("morning_digest.genai.Client") as client:
                result = generate_digest(project_root=root)

        self.assertEqual(result, "same payload")
        client.assert_not_called()

    def test_parses_exactly_ten_unique_words(self) -> None:
        items = [
            {
                "word": f"単語{i}",
                "reading": "たんご",
                "meaning_ko": f"단어{i}",
                "example_ja": f"単語{i}を使います。",
                "example_ko": f"단어{i}를 사용합니다.",
            }
            for i in range(10)
        ]
        parsed = parse_vocabulary_response("```json\n" + __import__("json").dumps(items, ensure_ascii=False) + "\n```")
        self.assertEqual(len(parsed), 10)

    def test_rejects_duplicate_words(self) -> None:
        items = [
            {
                "word": "勉強",
                "reading": "べんきょう",
                "meaning_ko": "공부",
                "example_ja": "日本語を勉強します。",
                "example_ko": "일본어를 공부합니다.",
            }
            for _ in range(10)
        ]
        with self.assertRaises(ValueError):
            parse_vocabulary_response(__import__("json").dumps(items, ensure_ascii=False))

    def test_rejects_a_word_sent_in_an_earlier_digest(self) -> None:
        items = [
            {
                "word": f"単語{i}", "reading": "たんご", "meaning_ko": "단어",
                "example_ja": f"単語{i}です。", "example_ko": "단어입니다.",
            }
            for i in range(10)
        ]
        with self.assertRaises(ValueError):
            parse_vocabulary_response(
                json.dumps(items, ensure_ascii=False), excluded_words={"単語0"}
            )

    def test_rejects_romaji_reading(self) -> None:
        items = [
            {
                "word": f"言葉{i}",
                "reading": "kotoba",
                "meaning_ko": "말",
                "example_ja": f"言葉{i}です。",
                "example_ko": "말입니다.",
            }
            for i in range(10)
        ]
        with self.assertRaises(ValueError):
            parse_vocabulary_response(__import__("json").dumps(items, ensure_ascii=False))

    def test_rejects_word_absent_from_saved_conversation(self) -> None:
        items = [
            {
                "word": f"言葉{i}",
                "reading": "ことば",
                "meaning_ko": "말",
                "example_ja": f"言葉{i}です。",
                "example_ko": "말입니다.",
            }
            for i in range(10)
        ]
        with self.assertRaises(ValueError):
            parse_vocabulary_response(
                __import__("json").dumps(items, ensure_ascii=False),
                source_text="今日は学校へ行きます。",
            )

    def test_formats_telegram_digest(self) -> None:
        items = [
            {"word": "勉強", "reading": "べんきょう", "meaning_ko": "공부", "example_ja": "日本語を勉強します。", "example_ko": "일본어를 공부합니다."}
        ]
        text = format_digest(items)
        self.assertIn("오늘의 일본어 10단어", text)
        self.assertIn("勉強（べんきょう）", text)
        self.assertIn("日本語を勉強します。", text)


if __name__ == "__main__":
    unittest.main()
