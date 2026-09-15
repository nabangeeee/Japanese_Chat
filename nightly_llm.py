"""Metered OpenAI calls for nightly experiments, separate from user traffic.

Conservative short-context rates: $13/M input (covers $12.50 cache writes)
and $50/M output; standard tier, no tools, bounded text-only requests.
Reservations survive interrupted calls. This is a local guard, not an account
billing cap; provider price changes require updating these constants.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
from typing import Any
import uuid
from zoneinfo import ZoneInfo

from openai import OpenAI

MODEL = 'gpt-6-astra'
INPUT_MICRO_USD = 13
OUTPUT_MICRO_USD = 50
MAX_DAILY_MICRO_USD = 1_000_000


class BudgetExceeded(RuntimeError):
    """The next call cannot be safely funded within the daily cap."""


class BudgetedLLM:
    def __init__(self, project_root: Path, api_key: str, *, limit_usd: Decimal | str = Decimal('1')):
        amount = Decimal(str(limit_usd))
        if not amount.is_finite() or not 0 < amount <= 1:
            raise ValueError('Nightly limit must be positive and at most $1')
        self.limit = int(amount * MAX_DAILY_MICRO_USD)
        self.root = Path(project_root) / 'scratch' / 'nightly_learning'
        self.api_key = api_key

    def _day(self):
        return datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()

    @contextmanager
    def _ledger(self, day):
        directory = self.root / day
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / 'budget.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            path = directory / 'budget.json'
            state = json.loads(path.read_text()) if path.exists() else {
                'charged_micro_usd': 0, 'reservations': {}, 'calls': 0,
            }
            if (not isinstance(state, dict)
                    or any(type(state.get(key)) is not int or state[key] < 0
                           for key in ('charged_micro_usd', 'calls'))
                    or not isinstance(state.get('reservations'), dict)
                    or any(type(value) is not int or value < 0
                           for value in state['reservations'].values())):
                raise ValueError('Invalid budget ledger; manual inspection required')
            yield state, path

    def _save(self, path, state):
        temporary = path.with_suffix('.tmp-' + uuid.uuid4().hex)
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(state, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)

    def summary(self):
        day = self._day()
        with self._ledger(day) as (state, _):
            return {'day': day, 'limit_usd': self.limit / MAX_DAILY_MICRO_USD,
                    'charged_usd': state['charged_micro_usd'] / MAX_DAILY_MICRO_USD,
                    'reserved_usd': sum(state['reservations'].values()) / MAX_DAILY_MICRO_USD,
                    'calls': state['calls']}

    def generate(self, prompt, *, instructions='', max_output_tokens=768, json_schema=None):
        if not isinstance(prompt, str) or not isinstance(instructions, str):
            raise ValueError('Only text input is allowed')
        if type(max_output_tokens) is not int or not 16 <= max_output_tokens <= 2048:
            raise ValueError('Output token limit must be 16..2048')
        kwargs: dict[str, Any] = dict(model=MODEL, input=prompt, instructions=instructions,
                      reasoning={'effort': 'low'}, max_output_tokens=max_output_tokens,
                      store=False, service_tier='default')
        if json_schema is not None:
            kwargs['text'] = {'format': {'type': 'json_schema', 'name': 'nightly',
                                        'strict': True, 'schema': json_schema}}
        encoded = json.dumps(kwargs, ensure_ascii=False).encode('utf-8')
        if len(encoded) > 16000:
            raise ValueError('Nightly request is too large')
        # UTF-8 bytes upper-bound byte-level text tokens, plus framing allowance.
        reserved = (len(encoded) + 1024) * INPUT_MICRO_USD + max_output_tokens * OUTPUT_MICRO_USD
        day, reservation = self._day(), uuid.uuid4().hex
        with self._ledger(day) as (state, path):
            used = state['charged_micro_usd'] + sum(state['reservations'].values())
            if state.get('blocked') or used + reserved > self.limit:
                raise BudgetExceeded('Daily experiment budget exhausted; no request sent')
            state['reservations'][reservation] = reserved
            state['calls'] += 1
            self._save(path, state)
        # No SDK retries: every potentially billed attempt gets its own reservation.
        with OpenAI(api_key=self.api_key, base_url='https://api.openai.com/v1', timeout=15.0, max_retries=0) as client:
            response = client.responses.create(**kwargs)
        usage = response.usage
        if usage is not None:
            if any(type(value) is not int or value < 0 for value in (usage.input_tokens, usage.output_tokens)):
                raise ValueError('Invalid provider usage; reservation retained')
            actual = usage.input_tokens * INPUT_MICRO_USD + usage.output_tokens * OUTPUT_MICRO_USD
            with self._ledger(day) as (state, path):
                del state['reservations'][reservation]
                state['charged_micro_usd'] += actual
                if actual > reserved:
                    state['blocked'] = True
                self._save(path, state)
            if actual > reserved:
                raise BudgetExceeded('Usage exceeded conservative reservation; stopped for inspection')
        if response.status != 'completed' or not response.output_text.strip():
            raise RuntimeError('Nightly provider returned incomplete or empty output')
        return response.output_text
