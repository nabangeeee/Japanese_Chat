import unittest
from datetime import date, timedelta
from unittest.mock import patch
from types import SimpleNamespace

import app_e2e as qa


class AutomaticQATests(unittest.TestCase):
    def test_scenarios_cover_week_and_are_reproducible(self):
        start = date(2026, 10, 6)
        scenarios = [qa.daily_scenario(start + timedelta(days=i)) for i in range(7)]
        self.assertEqual(len({s[0] for s in scenarios}), 7)
        self.assertEqual(qa.daily_scenario(start), qa.daily_scenario(start))

    def test_regression_failure_is_not_reported_as_success(self):
        with patch.object(qa.subprocess, 'run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaises(qa.CheckFailed):
                qa.regression_checks()

    def test_ui_regression_failure_is_not_reported_as_success(self):
        with patch.object(qa.subprocess, 'run', side_effect=[
            SimpleNamespace(returncode=0), SimpleNamespace(returncode=1)
        ]):
            with self.assertRaises(qa.CheckFailed):
                qa.regression_checks()
