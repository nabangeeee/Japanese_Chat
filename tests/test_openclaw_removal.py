from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OpenClawRemovalTests(unittest.TestCase):
    def test_openclaw_code_and_routes_are_removed(self) -> None:
        checked_files = [ROOT / "main.py", ROOT / "database.py", ROOT / "README.md"]
        matches = []
        for path in checked_files:
            text = path.read_text(encoding="utf-8").lower()
            for marker in ("openclaw", "live_trends", "/api/trends"):
                if marker in text:
                    matches.append(f"{path.name}: {marker}")

        self.assertEqual(matches, [])
        self.assertFalse((ROOT / "openclaw_collector.py").exists())


if __name__ == "__main__":
    unittest.main()
