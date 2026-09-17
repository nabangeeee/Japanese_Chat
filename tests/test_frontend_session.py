from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(
    encoding="utf-8"
)


class FrontendSessionTests(unittest.TestCase):
    def test_roleplay_settings_flow(self):
        import subprocess
        result = subprocess.run(
            ['node', 'tests/roleplay_settings_harness.js'],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_stale_provider_key_is_cleared_on_settings_load(self):
        source = APP_JS.split('function loadSettings()', 1)[1].split('function applySettingsToUI', 1)[0]
        self.assertIn("state.settings.apiKey = ''", source)
        self.assertIn("localStorage.setItem('nihongoSettings'", source)

    def test_sources_render_as_safe_clickable_links(self):
        import subprocess
        self.assertIn('function renderAssistantText', APP_JS)
        source = APP_JS.split('function renderAssistantText', 1)[1].split('\nfunction ', 1)[0]
        script = '''const escapeHTML = s => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');\nfunction renderAssistantText''' + source + '''
const good = renderAssistantText('東京。 [出典 1](https://example.com/a?q=1&x=2)');
if (!good.includes('href="https://example.com/a?q=1&amp;x=2"') || !good.includes('rel="noopener noreferrer"')) throw Error(good);
const bad = renderAssistantText('<script> [出典 1](javascript:alert)');
if (bad.includes('<script>') || bad.includes('href=')) throw Error(bad);
'''
        subprocess.run(['node', '-e', script], check=True, capture_output=True, text=True)

    def test_refresh_starts_a_new_conversation(self) -> None:
        init_source = APP_JS.split("async function initSessionSystem()", 1)[1].split(
            "async function startNewSession", 1
        )[0]

        self.assertIn("await startNewSession(false)", init_source)
        self.assertIn(
            "sessionStorage.removeItem('nihongoActiveSessionId')", init_source
        )
        self.assertIn("localStorage.removeItem('nihongoMessages')", init_source)
        self.assertNotIn("lastActiveSessionId", init_source)
        self.assertNotIn("switchSession(", init_source)


if __name__ == "__main__":
    unittest.main()
