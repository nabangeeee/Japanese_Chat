"""Process the durable runtime-repair queue outside the web service."""
from __future__ import annotations

from autonomous_repair import process_pending_incidents
from notifications import send_telegram


def main() -> int:
    for report in process_pending_incidents():
        print(report)
        send_telegram(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
