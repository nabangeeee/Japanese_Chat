from __future__ import annotations

import unittest
from unittest.mock import patch

import main


class RuntimeRepairSchedulingTests(unittest.TestCase):
    @patch("main.enqueue_runtime_incident")
    def test_persists_incident_without_starting_an_agent(self, enqueue) -> None:
        main._schedule_autonomous_repair("traceback")
        enqueue.assert_called_once_with("traceback")


if __name__ == "__main__":
    unittest.main()
