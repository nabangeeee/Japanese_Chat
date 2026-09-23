"""Digest provenance uses literal dictionary forms, not guessed lemmas."""
import json
import unittest
from typing import Any

from morning_digest import parse_vocabulary_response


def vocabulary() -> list[dict[str, Any]]:
    return [
        dict(source_form=word, word=word, reading="ことば", meaning_ko="단어",
             example_ja="日本語です。", example_ko="일본어입니다.")
        for word in ("学校", "先生", "学生", "日本語", "本", "猫", "犬", "水", "食べる", "行く")
    ]


class DigestSourceIntegrityTests(unittest.TestCase):
    def test_required_fields_do_not_coerce_malformed_values_into_strings(self):
        for field in vocabulary()[0]:
            for value in (None, 1, True, [], {}, ["学校"]):
                with self.subTest(field=field, value=value):
                    items = vocabulary()
                    items[0][field] = value
                    with self.assertRaises(ValueError):
                        parse_vocabulary_response(json.dumps(items))

    def test_literal_dictionary_forms_retain_exact_provenance(self):
        items = vocabulary()
        self.assertEqual(
            parse_vocabulary_response(json.dumps(items), source_text=" ".join(x["word"] for x in items)),
            items,
        )

    def test_rejects_unrelated_or_inflected_source_instead_of_guessing_lemmas(self):
        for source in ("学校", "食べました", "食べた", "食べること"):
            with self.subTest(source=source):
                items = vocabulary()
                items[8]["source_form"] = source
                with self.assertRaises(ValueError):
                    parse_vocabulary_response(json.dumps(items), source_text=" ".join(x["word"] for x in items) + " " + source)

    def test_requires_nonempty_explicit_source_when_validating_conversation(self):
        for source in ("", " \t\n", None):
            with self.subTest(source=source):
                items = vocabulary()
                if source is None:
                    del items[0]["source_form"]
                else:
                    items[0]["source_form"] = source
                with self.assertRaises(ValueError):
                    parse_vocabulary_response(json.dumps(items), source_text=" ".join(x["word"] for x in items))
