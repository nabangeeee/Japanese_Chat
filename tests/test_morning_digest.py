from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from morning_digest import (

    format_digest,
    generate_digest,
    parse_vocabulary_response,
)


class MorningDigestTests(unittest.TestCase):
    def test_openai_structured_digest_persists_and_revalidates(self) -> None:
        import morning_digest
        import os
        self.assertTrue(hasattr(morning_digest, 'generate_text'), 'digest still uses old provider')
        items = [{'source_form':f'単語{i}', 'word':f'単語{i}', 'reading':'たんご', 'meaning_ko':'단어', 'example_ja':'単語です。', 'example_ko':'단어입니다.'} for i in range(10)]
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, {'OPENAI_API_KEY':'key'}), patch('morning_digest.recent_conversation_text', return_value=' '.join(x['word'] for x in items)), patch('morning_digest.generate_text') as generate:
            generate.side_effect = ['{"items": []}', json.dumps({'items':items})]
            root = Path(temp_dir)
            result = generate_digest(project_root=root)
            self.assertIn('10단어', result)
            self.assertEqual(generate.call_count, 2)
            schema = generate.call_args.kwargs['json_schema']
            self.assertFalse(schema['additionalProperties'])
            self.assertFalse(schema['$defs']['VocabularyItem']['additionalProperties'])
            saved = list((root/'scratch'/'digests').glob('????-??-??.json'))
            self.assertEqual(len(saved), 1)
            self.assertEqual(len(json.loads(saved[0].read_text())['items']), 10)
            self.assertEqual(generate_digest(project_root=root), result)
            self.assertEqual(generate.call_count, 2)

    def test_same_day_retry_reuses_persisted_payload_without_openai(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            digest_dir = root / "scratch" / "digests"
            digest_dir.mkdir(parents=True)
            day = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
            (digest_dir / f"{day}.json").write_text(
                json.dumps({"message": "same payload", "items": []}), encoding="utf-8"
            )
            with patch("morning_digest.generate_text") as client:
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
