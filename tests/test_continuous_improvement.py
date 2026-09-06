from __future__ import annotations

import json
import fcntl
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from continuous_improvement import (
    _contains_sensitive_artifacts,
    _finish_pushed_proposal,
    _git_push_target,
    _promote_verified_commit,
    _push_verified_commit,
    ImprovementSignal,
    approve_proposal,
    collect_metrics,
    create_proposal,
    reject_proposal,
)


class ContinuousImprovementTests(unittest.TestCase):
    def test_pushed_proposal_returns_failure_when_applied_state_cannot_persist(self) -> None:
        proposal = {"id": "IMP-20260907-aaaaaaaa", "status": "verified"}
        with patch(
            "continuous_improvement._save_proposal", side_effect=OSError("disk full")
        ), patch("continuous_improvement.send_telegram") as notify:
            result = _finish_pushed_proposal(
                proposal, Path("/tmp/state"), "b" * 40, notify=True
            )

        self.assertFalse(result)
        self.assertEqual(proposal["status"], "verified")
        self.assertNotIn("pushed_at", proposal)
        notify.assert_called_once()
        self.assertIn("상태 기록 실패", notify.call_args.args[0])
        self.assertNotIn("개선 완료", notify.call_args.args[0])

    def test_push_target_binds_full_checked_out_branch_and_origin_upstream(self) -> None:
        results = [
            subprocess.CompletedProcess([], 0, "refs/heads/release/v1\n", ""),
            subprocess.CompletedProcess(
                [], 0, "refs/heads/release/v1\0origin\0refs/heads/deploy/v1\n", ""
            ),
        ]
        with patch("continuous_improvement.subprocess.run", side_effect=results):
            target = _git_push_target(Path("/tmp/project"))

        self.assertEqual(target, ("refs/heads/release/v1", "refs/heads/deploy/v1"))

    def test_push_uses_atomic_exact_remote_lease(self) -> None:
        baseline = "a" * 40
        commit = "b" * 40
        results = [
            subprocess.CompletedProcess([], 0, f"{commit}\n", ""),
            subprocess.CompletedProcess([], 0, f"{baseline}\trefs/heads/main\n", ""),
            subprocess.CompletedProcess([], 0, "ok", ""),
            subprocess.CompletedProcess([], 0, f"{commit}\trefs/heads/main\n", ""),
        ]
        with patch("continuous_improvement.subprocess.run", side_effect=results) as run:
            pushed, error = _push_verified_commit(
                Path("/tmp/project"), commit, baseline,
                "refs/heads/main", "refs/heads/main",
            )

        self.assertTrue(pushed, error)
        push_command = run.call_args_list[2].args[0]
        self.assertIn(
            f"--force-with-lease=refs/heads/main:{baseline}", push_command,
        )
        self.assertEqual(push_command[-1], f"{commit}:refs/heads/main")

    def test_push_nonzero_exit_is_success_when_remote_readback_matches(self) -> None:
        baseline = "a" * 40
        commit = "b" * 40
        results = [
            subprocess.CompletedProcess([], 0, f"{commit}\n", ""),
            subprocess.CompletedProcess([], 0, f"{baseline}\trefs/heads/main\n", ""),
            subprocess.CompletedProcess([], 1, "", "connection lost"),
            subprocess.CompletedProcess([], 0, f"{commit}\trefs/heads/main\n", ""),
        ]
        with patch("continuous_improvement.subprocess.run", side_effect=results):
            pushed, error = _push_verified_commit(
                Path("/tmp/project"), commit, baseline,
                "refs/heads/main", "refs/heads/main",
            )

        self.assertTrue(pushed, error)

    def test_promotion_cas_rejects_bound_branch_movement(self) -> None:
        baseline = "a" * 40
        commit = "b" * 40
        candidate = Path("/tmp/candidate")
        results = [
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, f"{commit} {baseline}\n", ""),
            subprocess.CompletedProcess([], 0, "refs/heads/main\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 1, "", "cannot lock ref"),
        ]
        with patch("continuous_improvement._git_is_clean", return_value=True), patch(
            "continuous_improvement.subprocess.run", side_effect=results
        ) as run:
            promoted, error = _promote_verified_commit(
                Path("/tmp/project"), candidate, commit, baseline, "refs/heads/main"
            )

        self.assertFalse(promoted)
        self.assertIn("changed", error)
        self.assertEqual(
            run.call_args_list[-1].args[0],
            ["git", "update-ref", "refs/heads/main", commit, baseline],
        )

    def test_push_verified_commit_fails_closed_without_origin(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.py"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root,
                capture_output=True, text=True, check=True,
            ).stdout.strip()

            pushed, error = _push_verified_commit(
                root, commit, commit, "refs/heads/main", "refs/heads/main"
            )

        self.assertFalse(pushed)
        self.assertTrue(error)

    def test_verification_git_control_tampering_blocks_improvement_promotion(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "scratch" / "improvement"
            (root / ".git").mkdir()
            config = root / ".git" / "config"
            config.write_text("safe\n", encoding="utf-8")
            with patch("continuous_improvement._git_head", return_value="base123"):
                proposal = create_proposal(signal, state_dir=state_dir, project_root=root, notify=False)

            def tamper(_root: Path, _timeout: int = 300) -> bool:
                config.write_text("[core]\nfsmonitor = /tmp/evil\n", encoding="utf-8")
                return True

            completed = subprocess.CompletedProcess([], 0, "done", "")
            with patch("continuous_improvement._git_is_clean", return_value=True), patch(
                "continuous_improvement._git_head", return_value="base123"
            ), patch(
                "continuous_improvement._git_push_target",
                return_value=("refs/heads/main", "refs/heads/main"),
            ), patch("continuous_improvement.sandbox_runner_available", return_value=True), patch(
                "continuous_improvement.run_sandboxed_hermes", return_value=completed
            ), patch("continuous_improvement._create_worktree", return_value=root), patch(
                "continuous_improvement._changed_paths", return_value=["app.py", "tests/test_app.py"]
            ), patch("continuous_improvement._contains_sensitive_artifacts", return_value=False), patch(
                "continuous_improvement._verify_project", side_effect=tamper
            ), patch("continuous_improvement.run_sandboxed_command") as git_command, patch(
                "continuous_improvement._remove_worktree"
            ):
                result = approve_proposal(
                    proposal["id"], proposal["approval_token"],
                    approval_source="telegram", approver_chat_id="8876641974",
                    project_root=root, notify=False,
                )

        self.assertFalse(result)
        git_command.assert_not_called()

    def test_rejection_cannot_race_an_active_approval(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "scratch" / "improvement"
            proposal = create_proposal(signal, state_dir=state_dir, notify=False)
            lock_path = state_dir / "approval.lock"
            with lock_path.open("w", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse(reject_proposal(proposal["id"], project_root=root, notify=False))
            saved = json.loads((state_dir / "proposals" / f"{proposal['id']}.json").read_text())
        self.assertEqual(saved["status"], "pending")

    @unittest.skipIf(os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1", "host integration")
    def test_verified_improvement_is_committed_and_pushed_to_origin(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "project"
            remote = parent / "remote.git"
            root.mkdir()
            subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
            subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / ".gitignore").write_text("scratch/\n", encoding="utf-8")
            (root / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
            (root / "tests").mkdir()
            (root / "tests" / "test_app.py").write_text("# baseline\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "baseline"], cwd=root, check=True)
            subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=root, check=True)
            subprocess.run(["git", "push", "-qu", "origin", "main"], cwd=root, check=True)
            proposal = create_proposal(
                signal, state_dir=root / "scratch" / "improvement",
                project_root=root, notify=False,
            )

            def repair(_prompt: str, *, workspace: Path, **_kwargs: object) -> subprocess.CompletedProcess[str]:
                (workspace / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
                (workspace / "tests" / "test_app.py").write_text("# regression\n", encoding="utf-8")
                return subprocess.CompletedProcess([], 0, "done", "")

            with patch("continuous_improvement.sandbox_runner_available", return_value=True), patch(
                "continuous_improvement.run_sandboxed_hermes", side_effect=repair
            ), patch("continuous_improvement._verify_project", return_value=True):
                result = approve_proposal(
                    proposal["id"], proposal["approval_token"],
                    approval_source="telegram", approver_chat_id="8876641974",
                    project_root=root, notify=False,
                )

            saved = json.loads((root / "scratch" / "improvement" / "proposals" / f"{proposal['id']}.json").read_text())
            self.assertTrue(result, saved)
            self.assertEqual((root / "app.py").read_text(encoding="utf-8"), "VALUE = 2\n")
            self.assertTrue(subprocess.run(
                ["git", "log", "-1", "--pretty=%s", "--grep", proposal["id"]],
                cwd=root, capture_output=True, text=True, check=True,
            ).stdout.strip())
            local_head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            remote_head = subprocess.run(
                ["git", "rev-parse", "refs/heads/main"], cwd=remote,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertEqual(remote_head, local_head)

    def test_rejects_path_traversal_proposal_id(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.assertFalse(
                approve_proposal("../../outside", project_root=root, notify=False)
            )
            self.assertFalse(
                reject_proposal("../../outside", project_root=root, notify=False)
            )
            self.assertFalse((root.parent / "outside.json").exists())

    def test_sensitive_artifact_is_detected_even_when_git_ignores_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "nihongo_chat.db").write_bytes(b"private")
            self.assertTrue(_contains_sensitive_artifacts(root))

    def test_metrics_detect_duplicate_and_slow_responses(self) -> None:
        rows = [
            {"content": "はい、そうですね。", "quality_score": 8.0, "response_time_sec": 10.0}
            for _ in range(8)
        ] + [
            {"content": f"異なる返事{i}", "quality_score": 5.0, "response_time_sec": 2.0}
            for i in range(2)
        ]
        metrics = collect_metrics(rows, negative_feedback_count=2, feedback_count=5)
        self.assertGreater(metrics["duplicate_rate"], 0.5)
        self.assertGreaterEqual(metrics["p95_response_time_sec"], 10.0)
        self.assertEqual(metrics["low_quality_rate"], 0.2)

    def test_create_proposal_is_persisted_and_deduplicated(self) -> None:
        signal = ImprovementSignal(
            kind="duplicate_responses",
            title="반복 응답 감소",
            evidence="최근 응답의 중복률이 40%입니다.",
            acceptance_criteria=["중복률 회귀 테스트 통과"],
            baseline={"duplicate_rate": 0.4},
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            state_dir = Path(temp_dir)
            first = create_proposal(signal, state_dir=state_dir, notify=False)
            second = create_proposal(signal, state_dir=state_dir, notify=False)
            payload = json.loads((state_dir / "proposals" / f"{first['id']}.json").read_text())

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(payload["status"], "pending")

    def test_approval_refuses_dirty_repo_without_running_agent(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal = create_proposal(signal, state_dir=root / "scratch" / "improvement", notify=False)
            with patch("continuous_improvement._git_is_clean", return_value=False), patch(
                "continuous_improvement.subprocess.run"
            ) as run:
                result = approve_proposal(
                    proposal["id"], proposal["approval_token"],
                    approval_source="telegram", approver_chat_id="8876641974",
                    project_root=root, notify=False,
                )

        self.assertFalse(result)
        run.assert_not_called()

    def test_failed_approval_discards_isolated_worktree_and_marks_failed(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            state_dir = root / "scratch" / "improvement"
            failed = subprocess.CompletedProcess([], 1, "", "agent failed")
            with patch("continuous_improvement._git_head", return_value="base123"):
                proposal = create_proposal(
                    signal, state_dir=state_dir, project_root=root, notify=False
                )
            with patch("continuous_improvement._git_is_clean", return_value=True), patch(
                "continuous_improvement._git_head", return_value="base123"
            ), patch(
                "continuous_improvement._git_push_target",
                return_value=("refs/heads/main", "refs/heads/main"),
            ), patch("continuous_improvement.sandbox_runner_available", return_value=True), patch(
                "continuous_improvement.run_sandboxed_hermes", return_value=failed
            ), patch(
                "continuous_improvement._create_worktree", return_value=root
            ), patch("continuous_improvement._remove_worktree") as remove_worktree:
                result = approve_proposal(
                    proposal["id"], proposal["approval_token"],
                    approval_source="telegram", approver_chat_id="8876641974",
                    project_root=root, notify=False,
                )
            saved = json.loads((state_dir / "proposals" / f"{proposal['id']}.json").read_text())

        self.assertFalse(result)
        remove_worktree.assert_called_once_with(root, root)
        self.assertEqual(saved["status"], "failed")

    def test_approval_requires_token_bound_to_proposal_content(self) -> None:
        signal = ImprovementSignal("quality", "응답 품질", "근거", ["테스트"], {"score": 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal = create_proposal(
                signal, state_dir=root / "scratch" / "improvement",
                project_root=root, notify=False,
            )
            self.assertFalse(approve_proposal(
                proposal["id"], "wrong-token", project_root=root, notify=False
            ))

    def test_reject_marks_pending_proposal_rejected(self) -> None:
        signal = ImprovementSignal("latency", "응답 속도", "근거", ["테스트"], {"p95": 9})
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal = create_proposal(signal, state_dir=root / "scratch" / "improvement", notify=False)
            self.assertTrue(reject_proposal(proposal["id"], project_root=root, notify=False))
            saved = json.loads((root / "scratch" / "improvement" / "proposals" / f"{proposal['id']}.json").read_text())

        self.assertEqual(saved["status"], "rejected")


if __name__ == "__main__":
    unittest.main()
