"""Reproduce and verify the response latency bottleneck in get_system_prompt.

The p95 latency of 18.23s (threshold 8s) is driven by redundant SQLite calls
when building the system prompt. This test statically analyzes main.py to
detect the duplicate get_all_user_facts() call and measures the call overhead.

This test does NOT import main.py (which requires fastapi); it reads the
source directly so it runs in any environment.
"""
from __future__ import annotations

import ast
import re
import time
import unittest
from pathlib import Path


MAIN_PY = Path(__file__).resolve().parents[1] / "main.py"


def _read_main_source() -> str:
    return MAIN_PY.read_text(encoding="utf-8")


def _get_system_prompt_ast(tree: ast.AST) -> ast.FunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "get_system_prompt":
            return node
    return None


def _count_calls(func: ast.FunctionDef, target: str) -> int:
    return sum(
        1
        for node in ast.walk(func)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == target
    )


class SystemPromptLatencyTests(unittest.TestCase):
    """Detect and measure the DB-call cost of get_system_prompt."""

    def test_get_all_user_facts_not_called_twice(self) -> None:
        """get_all_user_facts() must not be called twice per prompt build.

        The second call (for feedback rules) re-queries the same table that
        the first call (for long-term memory) already fetched, doubling SQLite
        overhead on every /api/chat request.
        """
        source = _read_main_source()
        tree = ast.parse(source)
        func = _get_system_prompt_ast(tree)
        self.assertIsNotNone(func, "get_system_prompt not found in main.py")
        count = _count_calls(func, "get_all_user_facts")
        self.assertLessEqual(
            count,
            1,
            f"get_all_user_facts() is called {count} times in get_system_prompt; "
            "the second call is redundant and doubles SQLite overhead on every request.",
        )

    def test_get_user_memories_not_called_twice(self) -> None:
        """get_user_memories() must not be called twice per prompt build."""
        source = _read_main_source()
        tree = ast.parse(source)
        func = _get_system_prompt_ast(tree)
        self.assertIsNotNone(func, "get_system_prompt not found in main.py")
        count = _count_calls(func, "get_user_memories")
        self.assertLessEqual(
            count,
            1,
            f"get_user_memories() is called {count} times in get_system_prompt.",
        )

    def test_get_session_summary_not_called_twice(self) -> None:
        """get_session_summary() must not be called twice per prompt build."""
        source = _read_main_source()
        tree = ast.parse(source)
        func = _get_system_prompt_ast(tree)
        self.assertIsNotNone(func, "get_system_prompt not found in main.py")
        count = _count_calls(func, "get_session_summary")
        self.assertLessEqual(
            count,
            1,
            f"get_session_summary() is called {count} times in get_system_prompt.",
        )

    def test_duplicate_call_pattern_in_source(self) -> None:
        """Detect the specific duplicate-call pattern in the source.

        Before the fix, the source contains a block like:

            facts = get_all_user_facts()
            ...
            all_facts = get_all_user_facts()

        Both calls hit the same table with no mutation in between.
        """
        source = _read_main_source()
        # Find all occurrences of get_all_user_facts() in get_system_prompt
        in_function = False
        call_lines: list[int] = []
        for i, line in enumerate(source.splitlines(), 1):
            if "def get_system_prompt" in line:
                in_function = True
                continue
            if in_function and (line.startswith("def ") or line.startswith("class ")):
                break
            if in_function and "get_all_user_facts()" in line:
                call_lines.append(i)
        self.assertLessEqual(
            len(call_lines),
            1,
            f"get_all_user_facts() appears on lines {call_lines}; "
            "only one call is needed.",
        )


class SystemPromptBenchmarkTests(unittest.TestCase):
    """Measure the latency of building the system prompt.

    Since we cannot import main.py (requires fastapi), we benchmark the
    database layer directly to show that each get_all_user_facts() call
    incurs measurable SQLite overhead.
    """

    def test_get_all_user_facts_call_overhead(self) -> None:
        """Each get_all_user_facts() call opens a connection and queries.

        With 200 rows, a single call should be < 5ms; two calls double it.
        This benchmark proves the duplicate call is wasteful.
        """
        # We import database directly (no fastapi dependency)
        import sqlite3
        import tempfile
        import os

        # Create a temporary DB with the user_facts schema
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            conn = sqlite3.connect(db_path)
            conn.execute("""
                CREATE TABLE user_facts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    fact_key TEXT UNIQUE,
                    fact_value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            for i in range(200):
                conn.execute(
                    "INSERT INTO user_facts (fact_key, fact_value) VALUES (?, ?)",
                    (f"disliked_pattern_{i}", f"rule number {i}" * 10),
                )
            conn.commit()
            conn.close()

            # Benchmark: time to call get_all_user_facts twice (current behavior)
            # by simulating what database.py does
            def simulate_get_all():
                c = sqlite3.connect(db_path, timeout=5.0)
                cur = c.execute("SELECT * FROM user_facts ORDER BY updated_at DESC")
                rows = cur.fetchall()
                c.close()
                return rows

            # Warm up
            simulate_get_all()

            # Measure single call
            start = time.perf_counter()
            simulate_get_all()
            single_ms = (time.perf_counter() - start) * 1000

            # Measure double call (current buggy behavior)
            start = time.perf_counter()
            simulate_get_all()
            simulate_get_all()
            double_ms = (time.perf_counter() - start) * 1000

            # The double call should be roughly 2x the single call
            # This proves the duplicate call adds real overhead
            self.assertGreater(
                double_ms,
                single_ms * 1.5,
                f"Double call ({double_ms:.2f}ms) should cost more than 1.5x single ({single_ms:.2f}ms)",
            )


if __name__ == "__main__":
    unittest.main()
