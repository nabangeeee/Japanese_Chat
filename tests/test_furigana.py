from __future__ import annotations

import unittest
from pathlib import Path

from main import normalize_furigana_output


class FuriganaOutputTests(unittest.TestCase):
    def test_extracts_japanese_reading_from_english_wrapper(self) -> None:
        raw = "Here is the sentence with furigana:\n今日(きょう)は学校(がっこう)へ行(い)きます。"

        self.assertEqual(
            normalize_furigana_output(raw, "今日は学校へ行きます。"),
            "今日(きょう)は学校(がっこう)へ行(い)きます。",
        )

    def test_rejects_english_only_reading(self) -> None:
        self.assertEqual(
            normalize_furigana_output(
                "Kyou wa gakkou e ikimasu.",
                "今日は学校へ行きます。",
            ),
            "",
        )

    def test_rejects_kanji_without_hiragana_readings(self) -> None:
        self.assertEqual(
            normalize_furigana_output("今日は学校へ行きます。", "今日は学校へ行きます。"),
            "",
        )

    def test_accepts_kana_only_sentence_without_parentheses(self) -> None:
        self.assertEqual(
            normalize_furigana_output("こんにちは！", "こんにちは！"),
            "こんにちは！",
        )

    def test_frontend_refetches_invalid_cached_reading(self) -> None:
        frontend = (
            Path(__file__).resolve().parents[1] / "static" / "app.js"
        ).read_text(encoding="utf-8")

        self.assertIn("isValidFurigana(message.furigana, message.content)", frontend)


if __name__ == "__main__":
    unittest.main()
