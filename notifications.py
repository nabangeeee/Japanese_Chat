"""Telegram delivery through the configured Hermes gateway credentials."""
from __future__ import annotations

import os
import shutil
import subprocess


def send_telegram(message: str, *, timeout_seconds: int = 30) -> bool:
    """Send text to the configured Telegram home chat without exposing tokens."""
    hermes = shutil.which("hermes")
    if not hermes or not message.strip():
        return False
    target = os.getenv("HERMES_TELEGRAM_TARGET", "telegram")
    try:
        completed = subprocess.run(
            [hermes, "send", "--to", target, "--quiet", message],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )
        return completed.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
