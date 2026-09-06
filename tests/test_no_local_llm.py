from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LocalLlmRemovalTests(unittest.TestCase):
    def test_application_code_has_no_local_llm_integration(self) -> None:
        forbidden = ("ollama", "localhost:11434", "hermes3:3b", "vllm")
        source_files = [
            path
            for path in ROOT.rglob("*")
            if path.suffix in {".py", ".md", ".txt"}
            and ".venv" not in path.parts
            and ".git" not in path.parts
            and path != Path(__file__)
        ]

        matches = []
        for path in source_files:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            for marker in forbidden:
                if marker in text:
                    matches.append(f"{path.relative_to(ROOT)}: {marker}")

        self.assertEqual(matches, [])

    def test_runtime_errors_enter_durable_repair_queue(self) -> None:
        main_source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn("enqueue_runtime_incident", main_source)
        self.assertNotIn("run_autonomous_repair", main_source)
        self.assertNotIn("diagnose_with_hermes", main_source)


if __name__ == "__main__":
    unittest.main()
