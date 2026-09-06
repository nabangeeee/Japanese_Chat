from __future__ import annotations

import subprocess
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autonomous_repair import (
    _apply_verified_changes,
    _contains_sensitive_artifacts,
    _create_worktree,
    _git_head,
    _remove_worktree,
    enqueue_runtime_incident,
    process_pending_incidents,
    run_autonomous_repair,
)


class AutonomousRepairTests(unittest.TestCase):
    def test_verification_git_control_tampering_blocks_runtime_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".git").mkdir()
            config = root / ".git" / "config"
            config.write_text("safe\n", encoding="utf-8")
            completed = subprocess.CompletedProcess([], 0, "done", "")

            def tamper(_root: Path, _timeout: int) -> bool:
                config.write_text("[core]\nfsmonitor = /tmp/evil\n", encoding="utf-8")
                return True

            with patch("autonomous_repair._git_is_clean", return_value=True), patch(
                "autonomous_repair._git_head", return_value="abc123"
            ), patch("autonomous_repair.sandbox_runner_available", return_value=True), patch(
                "autonomous_repair.run_sandboxed_hermes", return_value=completed
            ), patch("autonomous_repair._create_worktree", return_value=root), patch(
                "autonomous_repair._has_regression_test_change", return_value=True
            ), patch("autonomous_repair._contains_sensitive_artifacts", return_value=False), patch(
                "autonomous_repair._verify_project", side_effect=tamper
            ), patch("autonomous_repair._apply_verified_changes") as apply, patch(
                "autonomous_repair._remove_worktree"
            ):
                result = run_autonomous_repair(
                    "failure", project_root=root, max_attempts=1, notify=False
                )

        self.assertFalse(result)
        apply.assert_not_called()

    @unittest.skipIf(os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1", "host integration")
    def test_verified_runtime_commit_applies_without_advancing_main_head(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("# baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "--", "app.py", "tests/test_app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            baseline = _git_head(root)
            self.assertIsNotNone(baseline)
            worktree = _create_worktree(root, str(baseline))
            self.assertIsNotNone(worktree)
            assert worktree is not None
            try:
                (worktree / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
                (worktree / "tests" / "test_app.py").write_text("# regression\n", encoding="utf-8")
                self.assertTrue(_apply_verified_changes(root, worktree, str(baseline)))
                self.assertEqual(_git_head(root), baseline)
                self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            finally:
                subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=root, check=True, capture_output=True)
                _remove_worktree(root, worktree)

    def test_runtime_incidents_are_deduplicated_and_retries_are_durable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("autonomous_repair._code_version", return_value="version123"):
                first = enqueue_runtime_incident("ValueError: boom 12345", project_root=root)
                second = enqueue_runtime_incident("ValueError: boom 67890", project_root=root)
            self.assertEqual(first, second)
            path = root / "scratch" / "self_healing" / "incidents" / f"{first}.json"
            with patch("autonomous_repair._git_is_clean", return_value=True), patch(
                "autonomous_repair._git_head", return_value="abc123"
            ), patch(
                "autonomous_repair._code_version", return_value="version123"
            ), patch("autonomous_repair.run_autonomous_repair", return_value=False) as repair:
                process_pending_incidents(project_root=root)
                process_pending_incidents(project_root=root)
                reports = process_pending_incidents(project_root=root)
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(repair.call_count, 3)
        self.assertEqual(payload["attempts"], 3)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(len(reports), 1)
        self.assertNotIn("boom", str(payload["error_trace"]))

    def test_sensitive_artifact_in_isolated_worktree_blocks_application(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("do-not-read", encoding="utf-8")
            self.assertTrue(_contains_sensitive_artifacts(root))

    def test_retries_at_most_three_times_and_verifies_each_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            hermes_result = subprocess.CompletedProcess([], 0, "done", "")
            with patch("autonomous_repair._git_is_clean", return_value=True), patch(
                "autonomous_repair._git_head", return_value="abc123"
            ), patch("autonomous_repair.sandbox_runner_available", return_value=True), patch(
                "autonomous_repair.run_sandboxed_hermes", return_value=hermes_result
            ) as run, patch(
                "autonomous_repair._verify_project", side_effect=[False, False, True]
            ) as verify, patch(
                "autonomous_repair._create_worktree", return_value=root
            ), patch(
                "autonomous_repair._changed_paths",
                return_value=["app.py", "tests/test_app.py"],
            ), patch("autonomous_repair.snapshot_candidate_files", return_value=True), patch(
                "autonomous_repair._apply_verified_changes", return_value=True
            ), patch(
                "autonomous_repair._remove_worktree"
            ):
                result = run_autonomous_repair(
                    "Traceback: sample failure",
                    project_root=root,
                    timeout_seconds=90,
                    max_attempts=3,
                    notify=False,
                )

        self.assertTrue(result)
        self.assertEqual(run.call_count, 3)
        self.assertEqual(verify.call_count, 3)
        self.assertIn("untrusted diagnostic data", run.call_args.args[0])

    def test_discards_isolated_worktree_after_three_failed_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            failed = subprocess.CompletedProcess([], 1, "", "failed")
            with patch("autonomous_repair._git_is_clean", return_value=True), patch(
                "autonomous_repair._git_head", return_value="abc123"
            ), patch("autonomous_repair.sandbox_runner_available", return_value=True), patch(
                "autonomous_repair.run_sandboxed_hermes", return_value=failed
            ), patch("autonomous_repair._verify_project") as verify, patch(
                "autonomous_repair._create_worktree", return_value=root
            ), patch("autonomous_repair._remove_worktree") as remove_worktree:
                result = run_autonomous_repair("failure", project_root=root, notify=False)

        self.assertFalse(result)
        verify.assert_not_called()
        self.assertEqual(remove_worktree.call_count, 3)
        remove_worktree.assert_called_with(root.resolve(), root)

    def test_refuses_to_touch_a_dirty_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "autonomous_repair._git_is_clean", return_value=False
        ), patch("autonomous_repair.subprocess.run") as run:
            result = run_autonomous_repair(
                "failure", project_root=Path(temp_dir), notify=False
            )

        self.assertFalse(result)
        run.assert_not_called()

    def test_returns_false_without_hermes_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "autonomous_repair._git_is_clean", return_value=True
        ), patch("autonomous_repair._git_head", return_value="abc123"), patch(
            "autonomous_repair.sandbox_runner_available", return_value=False
        ):
            self.assertFalse(
                run_autonomous_repair(
                    "failure", project_root=Path(temp_dir), notify=False
                )
            )

    def test_incident_prompt_forbids_credentials_and_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            completed = subprocess.CompletedProcess([], 0, "done", "")
            with patch("autonomous_repair._git_is_clean", return_value=True), patch(
                "autonomous_repair._git_head", return_value="abc123"
            ), patch("autonomous_repair.sandbox_runner_available", return_value=True), patch(
                "autonomous_repair.run_sandboxed_hermes", return_value=completed
            ) as run, patch("autonomous_repair._verify_project", return_value=True), patch(
                "autonomous_repair._create_worktree", return_value=root
            ), patch("autonomous_repair._has_regression_test_change", return_value=True), patch(
                "autonomous_repair._apply_verified_changes", return_value=True
            ), patch(
                "autonomous_repair._remove_worktree"
            ):
                run_autonomous_repair(
                    "secret-looking diagnostic", project_root=root, notify=False
                )

            prompt = run.call_args.args[0]

        self.assertIn("Do not read or modify .env", prompt)
        self.assertIn("Do not commit or push", prompt)
        self.assertIn("Write a failing regression test first", prompt)


if __name__ == "__main__":
    unittest.main()
