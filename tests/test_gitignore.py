import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GitignoreTests(unittest.TestCase):
    def test_sqlite_database_and_sidecars_are_ignored(self):
        paths = [
            "nihongo_chat.db",
            "nihongo_chat.db-wal",
            "nihongo_chat.db-shm",
            "nihongo_chat.db-journal",
            "nested/test.db-wal",
            "nested/test.db-shm",
            "nested/test.db-journal",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            subprocess.run(["git", "init", "-q", temp_dir], check=True)
            shutil.copyfile(ROOT / ".gitignore", Path(temp_dir) / ".gitignore")
            result = subprocess.run(
                ["git", "check-ignore", "--no-index", "--stdin"],
                input="\n".join(paths + ["main.py", "tests/test_gitignore.py"]) + "\n",
                cwd=temp_dir, capture_output=True, text=True, check=True,
            )
        self.assertEqual(set(result.stdout.splitlines()), set(paths))
