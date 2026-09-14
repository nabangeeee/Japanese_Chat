"""Offline citation regression coverage across provider, storage, and UI."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import database
from llm_provider import generate_text
from main import clean_japanese_text


APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(
    encoding="utf-8"
)


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs))


def generate_with_citations(urls):
    # Only the external SDK boundary is mocked; adapter logic remains real.
    annotations = [SimpleNamespace(type="url_citation", url=url) for url in urls]
    messages = [
        SimpleNamespace(type="reasoning"),
        SimpleNamespace(type="web_search_call"),
        *[
            SimpleNamespace(type="message", content=[SimpleNamespace(
                type="output_text", annotations=[annotation],
            )])
            for annotation in annotations
        ],
    ]
    with patch("llm_provider.OpenAI") as factory:
        factory.return_value.__enter__.return_value.responses.create.return_value = (
            SimpleNamespace(status="completed", output_text="東京です。", output=messages)
        )
        return generate_text("test-key", "news", web_search=True)


def render_links(text):
    # Match the existing frontend tests: execute the production renderer in Node.
    renderer = APP_JS.split("function renderAssistantText", 1)[1].split("\nfunction ", 1)[0]
    script = """
const fs = require('fs');
const escapeHTML = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
function renderAssistantText""" + renderer + """
process.stdout.write(renderAssistantText(JSON.parse(fs.readFileSync(0, 'utf8'))));
"""
    result = subprocess.run(
        ["node", "-e", script], input=json.dumps(text),
        capture_output=True, text=True, check=True,
    )
    parsed = LinkParser()
    parsed.feed(result.stdout)
    return parsed


class CitationRegressionTests(unittest.TestCase):
    def test_url_punctuation_unicode_and_quotes_survive_cleanup_and_rendering(self):
        cases = [
            ("https://example.com/a(b)", "https://example.com/a%28b%29"),
            ("https://example.com/東京?q=日本語", "https://example.com/%E6%9D%B1%E4%BA%AC?q=%E6%97%A5%E6%9C%AC%E8%AA%9E"),
            ('https://example.com/a?x="hi"&y=\'ok\'', "https://example.com/a?x=%22hi%22&y=%27ok%27"),
            ("https://example.com/a%20b?q=one+two#part", "https://example.com/a%20b?q=one+two#part"),
        ]
        for raw_url, expected_url in cases:
            with self.subTest(url=raw_url):
                cleaned = clean_japanese_text(generate_with_citations([raw_url]))
                self.assertEqual(cleaned, f"東京です。 [出典 1]({expected_url})")
                links = render_links(cleaned).links
                self.assertEqual(len(links), 1)
                self.assertEqual(links[0]["href"], expected_url)
                self.assertEqual(links[0]["target"], "_blank")
                self.assertEqual(set(links[0]["rel"].split()), {"noopener", "noreferrer"})

    def test_duplicate_annotations_are_deduplicated_in_first_seen_order(self):
        first = "https://example.com/first"
        second = "https://example.com/second"
        cleaned = clean_japanese_text(generate_with_citations([first, first, second, first, second]))
        self.assertEqual(cleaned, f"東京です。 [出典 1]({first}) [出典 2]({second})")
        self.assertEqual([link["href"] for link in render_links(cleaned).links], [first, second])

    def test_unsafe_annotation_schemes_never_become_source_links(self):
        unsafe = [
            "javascript:alert(1)", "data:text/html,<script>alert(1)</script>",
            "file:///etc/passwd", "ftp://example.com/file", "//example.com/path",
        ]
        for url in unsafe:
            with self.subTest(url=url):
                generated = generate_with_citations([url, "https://example.com/safe"])
                self.assertEqual(generated, "東京です。 [出典 1](https://example.com/safe)")
                self.assertEqual(len(render_links(generated).links), 1)

    def test_frontend_escapes_prose_and_rejects_unsafe_link_schemes(self):
        text = '<script>alert(1)</script> [出典 1](javascript:alert) [出典 2](data:text/html,evil)'
        parsed = render_links(text)
        self.assertEqual(parsed.tags, [])
        self.assertEqual(parsed.links, [])

    def test_frontend_url_quotes_cannot_escape_href_attribute(self):
        text = '[出典 1](https://example.com/"onmouseover="alert\'x)'
        parsed = render_links(text)
        self.assertEqual(parsed.tags, ["a"])
        self.assertEqual(len(parsed.links), 1)
        link = parsed.links[0]
        self.assertEqual(link["href"], 'https://example.com/"onmouseover="alert\'x')
        self.assertNotIn("onmouseover", link)
        self.assertEqual(link["onclick"], "event.stopPropagation()")
        self.assertEqual(set(link), {"href", "target", "rel", "onclick"})

    def test_stored_and_reloaded_citations_remain_clickable_and_unchanged(self):
        url = 'https://example.com/東京(a)?q="b"&x=1'
        expected_url = "https://example.com/%E6%9D%B1%E4%BA%AC%28a%29?q=%22b%22&x=1"
        cleaned = clean_japanese_text(generate_with_citations([url, url]))
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(database, "DB_PATH", str(Path(temp_dir) / "citations.db")):
                database.init_db()
                database.create_session("citation-session", "test", "ユキ", "beginner", "free")
                database.save_message("citation-message", "citation-session", "assistant", cleaned)
                loaded = database.get_session_messages("citation-session")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["content"], cleaned)
        self.assertEqual(loaded[0]["role"], "assistant")
        self.assertEqual([link["href"] for link in render_links(loaded[0]["content"]).links], [expected_url])


if __name__ == "__main__":
    unittest.main()
