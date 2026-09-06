from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sandboxed_hermes import (
    _sandbox_profile,
    run_sandboxed_command,
    run_sandboxed_hermes,
    snapshot_candidate_files,
)


class SandboxedHermesTests(unittest.TestCase):
    @staticmethod
    def _workspace_parent() -> Path:
        if os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1":
            return Path(os.environ["TMPDIR"])
        return Path("/tmp") if Path.cwd().is_relative_to(Path.home()) else Path.cwd()

    @unittest.skipIf(os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1", "host integration")
    def test_verification_command_cannot_write_clone_or_user_home(self) -> None:
        confined_parent = not Path.cwd().is_relative_to(Path.home())
        target = (Path.cwd() if confined_parent else Path.home()) / ".nihongo_sandbox_escape_test"
        temp_parent = Path.cwd() if confined_parent else Path("/tmp")
        target.unlink(missing_ok=True)
        try:
            with tempfile.TemporaryDirectory(prefix="sandbox-test-", dir=temp_parent) as temp_dir:
                workspace = Path(temp_dir)
                inside = run_sandboxed_command(
                    ["/usr/bin/python3", "-c", "from pathlib import Path; Path('inside.txt').write_text('no')"],
                    workspace=workspace, timeout_seconds=30,
                )
                outside = run_sandboxed_command(
                    ["/usr/bin/python3", "-c", f"from pathlib import Path; Path({str(target)!r}).write_text('no')"],
                    workspace=workspace, timeout_seconds=30,
                )
                self.assertNotEqual(inside.returncode, 0)
                self.assertNotEqual(outside.returncode, 0)
                self.assertFalse((workspace / "inside.txt").exists())
                self.assertFalse(target.exists())
        finally:
            target.unlink(missing_ok=True)

    def test_untrusted_commands_cannot_modify_git_controls(self) -> None:
        workspace = Path("/tmp/nihongo-sandbox-workspace")
        agent_home = Path("/tmp/nihongo-sandbox-home")

        restricted = _sandbox_profile(workspace, agent_home, allow_proxy=False)
        agent = _sandbox_profile(
            workspace, agent_home, allow_proxy=True, allow_workspace_write=True,
        )
        trusted_git = _sandbox_profile(
            workspace, agent_home, allow_proxy=False, allow_git_write=True,
        )

        git_deny = f'(deny file-write* (subpath "{(workspace / ".git").resolve()}"))'
        self.assertIn(git_deny, restricted)
        self.assertIn(git_deny, agent)
        self.assertNotIn(git_deny, trusted_git)
        workspace_allow = f'(allow file-write* (subpath "{workspace.resolve()}"))'
        self.assertNotIn(workspace_allow, restricted)
        self.assertIn(workspace_allow, agent)

    def test_candidate_snapshot_is_detached_from_agent_workspace(self) -> None:
        parent = self._workspace_parent()
        with tempfile.TemporaryDirectory(dir=parent) as source_dir, tempfile.TemporaryDirectory(
            dir=parent
        ) as target_dir:
            source = Path(source_dir)
            target = Path(target_dir)
            (source / "app.py").write_text("verified\n", encoding="utf-8")

            self.assertTrue(snapshot_candidate_files(source, target, ["app.py"]))
            (source / "app.py").write_text("late mutation\n", encoding="utf-8")

            self.assertEqual((target / "app.py").read_text(encoding="utf-8"), "verified\n")

    def test_candidate_snapshot_rejects_symlinks(self) -> None:
        parent = self._workspace_parent()
        with tempfile.TemporaryDirectory(dir=parent) as source_dir, tempfile.TemporaryDirectory(
            dir=parent
        ) as target_dir:
            source = Path(source_dir)
            (source / "app.py").symlink_to("/etc/hosts")
            self.assertFalse(snapshot_candidate_files(source, Path(target_dir), ["app.py"]))

    @unittest.skipIf(os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1", "host integration")
    def test_runner_uses_isolated_home_and_loopback_only_network(self) -> None:
        with tempfile.TemporaryDirectory(dir=self._workspace_parent()) as temp_dir:
            workspace = Path(temp_dir)
            completed = subprocess.CompletedProcess([], 0, "ok", "")
            with patch("sandboxed_hermes.sandbox_runner_available", return_value=True), patch(
                "sandboxed_hermes._proxy_is_ready", return_value=True
            ), patch.dict(os.environ, {"GEMINI_API_KEY": "secret", "SSH_AUTH_SOCK": "/secret/socket"}), patch(
                "sandboxed_hermes.subprocess.run", return_value=completed
            ) as run:
                result = run_sandboxed_hermes(
                    "safe task", workspace=workspace,
                    timeout_seconds=60, max_turns=2,
                )

        self.assertEqual(result.returncode, 0)
        command = run.call_args.args[0]
        profile = command[command.index("-p") + 1]
        environment = run.call_args.kwargs["env"]
        self.assertIn("(deny network*)", profile)
        self.assertIn("(deny file-write*)", profile)
        self.assertIn('/usr/bin/security', profile)
        self.assertIn('localhost:8645', profile)
        self.assertIn(f'(deny file-read* (subpath "{Path.home()}"', profile)
        self.assertNotIn("GEMINI_API_KEY", environment)
        self.assertNotIn("SSH_AUTH_SOCK", environment)
        self.assertNotEqual(environment["HOME"], str(Path.home()))
        self.assertIn("--yolo", command)

    def test_runner_refuses_workspace_inside_user_home(self) -> None:
        with patch("sandboxed_hermes.sandbox_runner_available", return_value=True), patch(
            "sandboxed_hermes._proxy_is_ready", return_value=True
        ), patch("sandboxed_hermes.subprocess.run") as run:
            result = run_sandboxed_hermes(
                "task", workspace=Path.home(), timeout_seconds=60, max_turns=2
            )

        self.assertEqual(result.returncode, 77)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
