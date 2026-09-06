from __future__ import annotations

import unittest
from pathlib import Path


APP_JS = (Path(__file__).resolve().parents[1] / "static" / "app.js").read_text(
    encoding="utf-8"
)


class FrontendSessionTests(unittest.TestCase):
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
