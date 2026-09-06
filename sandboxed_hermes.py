"""Run Hermes with filesystem and network confinement on macOS."""
from __future__ import annotations

import os
import stat
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

PROXY_URL = "http://127.0.0.1:8645/v1"
DEFAULT_MODEL = "meituan/longcat-2.0:free"
MAX_SNAPSHOT_BYTES = 25 * 1024 * 1024


def _seatbelt_literal(value: Path) -> str:
    return str(value.resolve()).replace("\\", "\\\\").replace('"', '\\"')


def sandbox_runner_available() -> bool:
    root = Path.home() / ".hermes" / "hermes-agent"
    return bool(
        shutil.which("sandbox-exec")
        and (root / "venv" / "bin" / "python").exists()
        and (root / "hermes").exists()
    )


def _proxy_is_ready() -> bool:
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        request = urllib.request.Request(
            f"{PROXY_URL}/models",
            headers={"Authorization": "Bearer sandbox-proxy", "User-Agent": "curl/8.7.1"},
        )
        with opener.open(request, timeout=3) as response:
            return response.status == 200
    except (OSError, TimeoutError):
        return False


def _sandbox_profile(
    workspace: Path, agent_home: Path, *, allow_proxy: bool,
    allow_workspace_write: bool = False, allow_git_write: bool = False,
) -> str:
    user_home = Path.home().resolve()
    hermes_root = user_home / ".hermes" / "hermes-agent"
    uv_root = user_home / ".local" / "share" / "uv"
    project_venv = Path(__file__).resolve().parent / ".venv"
    writable_parents = {
        parent.resolve() for path in (workspace, agent_home)
        for parent in path.parents if parent != Path("/")
    }
    parent_rules = " ".join(
        f'(literal "{_seatbelt_literal(parent)}")'
        for parent in sorted(writable_parents, key=lambda item: len(item.parts))
    )
    readable_parents = {
        parent.resolve() for path in (workspace, agent_home, hermes_root, uv_root, project_venv)
        for parent in path.parents if parent != Path("/")
    }
    read_parent_rules = " ".join(
        f'(literal "{_seatbelt_literal(parent)}")'
        for parent in sorted(readable_parents, key=lambda item: len(item.parts))
    )
    network_rule = '(allow network-outbound (remote ip "localhost:8645"))' if allow_proxy else ""
    workspace_write_rule = (
        f'(allow file-write* (subpath "{_seatbelt_literal(workspace)}"))'
        if allow_workspace_write else ""
    )
    git_write_rule = (
        f'(allow file-write* (subpath "{_seatbelt_literal(workspace / ".git")}"))'
        if allow_git_write
        else f'(deny file-write* (subpath "{_seatbelt_literal(workspace / ".git")}"))'
    )
    return f"""(version 1)
(allow default)
(deny file-read* (subpath "{_seatbelt_literal(user_home)}") (subpath "/private/var/folders") (subpath "/private/tmp"))
(deny file-write*)
(allow file-read* (subpath "{_seatbelt_literal(workspace)}") (subpath "{_seatbelt_literal(agent_home)}") (subpath "{_seatbelt_literal(hermes_root)}") (subpath "{_seatbelt_literal(uv_root)}") (subpath "{_seatbelt_literal(project_venv)}"))
(allow file-read* {read_parent_rules})
{workspace_write_rule}
(allow file-write* (subpath "{_seatbelt_literal(agent_home)}") (literal "/dev/null") {parent_rules})
{git_write_rule}
(deny process-exec (literal "/usr/bin/security") (literal "/usr/bin/osascript") (literal "/usr/bin/ssh") (literal "/usr/bin/scp"))
(deny network*)
{network_rule}
"""


def _sandbox_environment(agent_home: Path) -> dict[str, str]:
    project_venv = Path(__file__).resolve().parent / ".venv"
    return {
        "HOME": str(agent_home),
        "HERMES_HOME": str(agent_home),
        "TMPDIR": str(agent_home / "tmp"),
        "PYTHONPYCACHEPREFIX": str(agent_home / "pycache"),
        "PATH": f"{project_venv / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": os.getenv("LANG", "en_US.UTF-8"),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "PYTHONUNBUFFERED": "1",
        "NIHONGO_SANDBOX_ACTIVE": "1",
    }


def _timeout_result(command: list[str], exc: subprocess.TimeoutExpired) -> subprocess.CompletedProcess[str]:
    stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "sandboxed command timed out")
    return subprocess.CompletedProcess(command, 124, stdout, stderr)


def snapshot_candidate_files(
    source_workspace: Path, target_workspace: Path, paths: list[str]
) -> bool:
    """Copy a bounded regular-file snapshot into an isolated trusted clone."""
    source_root = source_workspace.resolve()
    target_root = target_workspace.resolve()
    total = 0
    try:
        for relative in paths:
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                return False
            source = source_root / relative_path
            target = target_root / relative_path
            if not target.parent.resolve().is_relative_to(target_root):
                return False
            try:
                source_info = source.lstat()
            except FileNotFoundError:
                if target.is_symlink() or target.is_file():
                    target.unlink()
                elif target.exists():
                    return False
                continue
            if not stat.S_ISREG(source_info.st_mode):
                return False
            descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                opened_info = os.fstat(descriptor)
                if not stat.S_ISREG(opened_info.st_mode):
                    return False
                chunks: list[bytes] = []
                while chunk := os.read(descriptor, 1024 * 1024):
                    total += len(chunk)
                    if total > MAX_SNAPSHOT_BYTES:
                        return False
                    chunks.append(chunk)
            finally:
                os.close(descriptor)
            if target.is_symlink() or (target.exists() and not target.is_file()):
                return False
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"".join(chunks))
        return True
    except (OSError, ValueError):
        return False


def run_sandboxed_command(
    command: list[str], *, workspace: Path, timeout_seconds: int,
    allow_git_write: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Execute untrusted verification or clone-side Git under Seatbelt."""
    workspace = workspace.resolve()
    if workspace.is_relative_to(Path.home().resolve()) or not shutil.which("sandbox-exec"):
        return subprocess.CompletedProcess(command, 77, "", "sandboxed command is unavailable")
    temp_parent = workspace if os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1" else Path("/tmp")
    agent_home = Path(tempfile.mkdtemp(prefix=".nihongo-verify-home-", dir=temp_parent)).resolve()
    try:
        (agent_home / "tmp").mkdir()
        (agent_home / "pycache").mkdir()
        sandbox_command = [
            "/usr/bin/sandbox-exec", "-p",
            _sandbox_profile(
                workspace, agent_home, allow_proxy=False,
                allow_git_write=allow_git_write,
            ),
            *command,
        ]
        try:
            return subprocess.run(
                sandbox_command, cwd=workspace, capture_output=True, text=True,
                timeout=timeout_seconds, shell=False, check=False,
                env=_sandbox_environment(agent_home),
            )
        except subprocess.TimeoutExpired as exc:
            return _timeout_result(sandbox_command, exc)
    finally:
        shutil.rmtree(agent_home, ignore_errors=True)


def run_sandboxed_hermes(
    prompt: str, *, workspace: Path, timeout_seconds: int, max_turns: int
) -> subprocess.CompletedProcess[str]:
    """Run a credential-free Hermes client confined to one isolated clone."""
    if not sandbox_runner_available():
        return subprocess.CompletedProcess([], 127, "", "macOS sandbox runner is unavailable")
    if not _proxy_is_ready():
        return subprocess.CompletedProcess([], 69, "", "local credential proxy is unavailable")

    workspace = workspace.resolve()
    user_home = Path.home().resolve()
    if workspace.is_relative_to(user_home):
        return subprocess.CompletedProcess([], 77, "", "workspace must be outside the user home")

    hermes_root = user_home / ".hermes" / "hermes-agent"
    temp_parent = workspace if os.getenv("NIHONGO_SANDBOX_ACTIVE") == "1" else Path("/tmp")
    agent_home = Path(tempfile.mkdtemp(prefix=".nihongo-hermes-home-", dir=temp_parent)).resolve()
    try:
        (agent_home / "tmp").mkdir()
        (agent_home / "config.yaml").write_text(
            "model:\n"
            f"  default: {os.getenv('NIHONGO_REPAIR_MODEL', DEFAULT_MODEL)}\n"
            "  provider: custom\n"
            f"  base_url: {PROXY_URL}\n"
            "  api_key: sandbox-proxy\n",
            encoding="utf-8",
        )
        query_path = agent_home / "task.md"
        query_path.write_text(prompt, encoding="utf-8")

        profile = _sandbox_profile(
            workspace, agent_home, allow_proxy=True, allow_workspace_write=True,
        )
        python = hermes_root / "venv" / "bin" / "python"
        hermes_script = hermes_root / "hermes"
        command = [
            "/usr/bin/sandbox-exec", "-p", profile,
            str(python), str(hermes_script), "chat",
            "--query-file", str(query_path), "--oneshot", "--quiet",
            "--provider", "custom", "--model",
            os.getenv("NIHONGO_REPAIR_MODEL", DEFAULT_MODEL),
            "--in", str(workspace), "--toolsets", "terminal,file",
            "--max-turns", str(max_turns), "--run-budget",
            str(max(30, timeout_seconds - 15)),
            "--ignore-rules", "--yolo", "--source", "tool",
        ]
        environment = _sandbox_environment(agent_home)
        try:
            return subprocess.run(
                command, cwd=workspace, capture_output=True, text=True,
                timeout=timeout_seconds, shell=False, check=False, env=environment,
            )
        except subprocess.TimeoutExpired as exc:
            return _timeout_result(command, exc)
    finally:
        shutil.rmtree(agent_home, ignore_errors=True)
