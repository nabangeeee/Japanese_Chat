from __future__ import annotations

from decimal import Decimal
import json
import importlib.util
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class NightlyBudgetTests(unittest.TestCase):
    def test_budget_reserves_before_call_and_settles_usage(self):
        self.assertIsNotNone(importlib.util.find_spec('nightly_llm'))
        from nightly_llm import BudgetedLLM, BudgetExceeded
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            call = sdk.return_value.__enter__.return_value.responses.create
            llm = BudgetedLLM(Path(tmp), 'fake-key')
            def respond(**kwargs):
                self.assertGreater(llm.summary()['reserved_usd'], 0)
                self.assertEqual(kwargs['model'], 'gpt-6-astra')
                self.assertFalse(kwargs['store'])
                self.assertEqual(kwargs['service_tier'], 'default')
                self.assertNotIn('tools', kwargs)
                return SimpleNamespace(status='completed', output_text='はい。', usage=SimpleNamespace(input_tokens=100, output_tokens=100))
            call.side_effect = respond
            self.assertEqual(llm.generate('こんにちは'), 'はい。')
            self.assertEqual(llm.summary()['reserved_usd'], 0)
            self.assertEqual(llm.summary()['charged_usd'], 0.0063)
            self.assertEqual(sdk.call_args.kwargs['max_retries'], 0)
            self.assertEqual(sdk.call_args.kwargs.get('base_url'), 'https://api.openai.com/v1')
            blocked = BudgetedLLM(Path(tmp), 'fake-key', limit_usd=Decimal('0.001'))
            with self.assertRaises(BudgetExceeded):
                blocked.generate('hello')
            self.assertEqual(call.call_count, 1)
            self.assertEqual(BudgetedLLM(Path(tmp), 'fake-key').summary()['calls'], 1)

    def test_corrupt_or_negative_ledger_fails_closed(self):
        from nightly_llm import BudgetedLLM
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status='completed', output_text='OK', usage=None)
            llm = BudgetedLLM(Path(tmp), 'fake-key')
            directory = llm.root / llm._day()
            directory.mkdir(parents=True)
            for payload in ['not-json', json.dumps({'charged_micro_usd': -1, 'reservations': {}, 'calls': 0}), json.dumps({'charged_micro_usd': 0, 'reservations': {'x': -5}, 'calls': 0})]:
                with self.subTest(payload=payload):
                    (directory / 'budget.json').write_text(payload)
                    with self.assertRaises((ValueError, RuntimeError)):
                        llm.generate('test')
            sdk.assert_not_called()

    def test_network_failure_retains_reservation_across_restarts(self):
        from nightly_llm import BudgetedLLM, BudgetExceeded
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            call = sdk.return_value.__enter__.return_value.responses.create
            call.side_effect = RuntimeError('connection lost')
            llm = BudgetedLLM(Path(tmp), 'fake-key', limit_usd=Decimal('0.08'))
            with self.assertRaisesRegex(RuntimeError, 'connection lost'):
                llm.generate('test')
            before = llm.summary()
            self.assertGreater(before['reserved_usd'], 0)
            with self.assertRaises(BudgetExceeded):
                BudgetedLLM(Path(tmp), 'fake-key', limit_usd=Decimal('0.08')).generate('test')
            self.assertEqual(call.call_count, 1)
            self.assertEqual(llm.summary(), before)

    def test_untrusted_usage_cannot_release_reservation(self):
        from nightly_llm import BudgetedLLM
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            sdk.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status='completed', output_text='OK', usage=SimpleNamespace(input_tokens=-1, output_tokens=0))
            llm = BudgetedLLM(Path(tmp), 'fake-key')
            with self.assertRaises(ValueError):
                llm.generate('test')
            self.assertGreater(llm.summary()['reserved_usd'], 0)

    def test_limits_and_payload_are_not_bypassable(self):
        from nightly_llm import BudgetedLLM
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            for amount in ['NaN', 'Infinity', '-1', '0', '1.01']:
                with self.subTest(amount=amount), self.assertRaises(ValueError):
                    BudgetedLLM(Path(tmp), 'fake-key', limit_usd=amount)
            llm = BudgetedLLM(Path(tmp), 'fake-key')
            with self.assertRaises(ValueError):
                llm.generate('あ' * 16000)
            with self.assertRaises(ValueError):
                llm.generate('test', max_output_tokens=100000)
            sdk.assert_not_called()

    def test_concurrent_call_cannot_spend_an_inflight_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from nightly_llm import BudgetedLLM, BudgetExceeded
        entered, release = Event(), Event()
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            def respond(**kwargs):
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test timed out')
                return SimpleNamespace(status='completed', output_text='OK', usage=None)
            sdk.return_value.__enter__.return_value.responses.create.side_effect = respond
            with ThreadPoolExecutor(max_workers=1) as executor:
                pending = executor.submit(BudgetedLLM(Path(tmp), 'key', limit_usd='0.08').generate, 'test')
                try:
                    self.assertTrue(entered.wait(5))
                    with self.assertRaises(BudgetExceeded):
                        BudgetedLLM(Path(tmp), 'key', limit_usd='0.08').generate('test')
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=5), 'OK')

    def test_unexpected_usage_overrun_halts_further_calls(self):
        from nightly_llm import BudgetedLLM, BudgetExceeded
        with tempfile.TemporaryDirectory() as tmp, patch('nightly_llm.OpenAI') as sdk:
            call = sdk.return_value.__enter__.return_value.responses.create
            call.return_value = SimpleNamespace(status='completed', output_text='OK', usage=SimpleNamespace(input_tokens=20000, output_tokens=100))
            llm = BudgetedLLM(Path(tmp), 'key')
            with self.assertRaises(BudgetExceeded):
                llm.generate('test')
            with self.assertRaises(BudgetExceeded):
                llm.generate('test')
            self.assertEqual(call.call_count, 1)
