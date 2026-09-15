import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class PromptTests(unittest.TestCase):
    def test_baseline_uses_literals_without_importing_application(self):
        self.assertIsNotNone(importlib.util.find_spec('nightly_learning'), 'nightly runner missing')
        from nightly_learning import baseline_prompt
        text = baseline_prompt(ROOT, 'beginner', 'food')
        self.assertIn('Japanese cuisine.', text)
        self.assertIn('Reply ONLY in Japanese.', text)
        self.assertNotIn('Memory Notes', text)
        self.assertNotIn('Feedback-Based', text)


class RunnerTests(unittest.TestCase):
    def test_invalid_judge_and_provider_failures_are_durable_without_proposal(self):
        import nightly_learning as n
        import tempfile
        from unittest.mock import patch
        class Broken(FakeLLM):
            def generate(self, prompt, *, instructions='', **kwargs):
                if instructions.startswith('JUDGE'):
                    return '{"A": {"naturalness": 99}, "B": {}}'
                return super().generate(prompt, instructions=instructions, **kwargs)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text((ROOT / 'main.py').read_text())
            with patch.object(n, '_snapshot', return_value={'head': 'a' * 40, 'dirty': ''}):
                report = n.run_nightly(project_root=root, llm=Broken())
                self.assertEqual(report['status'], 'incomplete')
                self.assertNotIn('proposal', report)
                self.assertEqual(n.run_nightly(project_root=root, llm=FakeLLM()), report)

    def test_validation_rejects_out_of_range_bool_and_oversized_candidate(self):
        import nightly_learning as n
        import tempfile
        import json
        from unittest.mock import patch
        for bad in (99, True, '4', float('nan'), 'oversized', 'empty'):
            with self.subTest(bad=bad), tempfile.TemporaryDirectory() as directory:
                class Invalid(FakeLLM):
                    def generate(self, prompt, *, instructions='', **kwargs):
                        if instructions.startswith('OPTIMIZER') and bad in ('oversized', 'empty'):
                            return json.dumps({'append': 'x' * 601 if bad == 'oversized' else ''})
                        if instructions.startswith('JUDGE'):
                            return json.dumps({label: {a: bad for a in n.AXES} for label in ('A', 'B')})
                        return super().generate(prompt, instructions=instructions, **kwargs)
                root = Path(directory)
                (root / 'main.py').write_text((ROOT / 'main.py').read_text())
                with patch.object(n, '_snapshot', return_value={'head': 'a' * 40, 'dirty': ''}):
                    result = n.run_nightly(project_root=root, llm=Invalid())
                self.assertEqual(result['status'], 'incomplete')
                self.assertNotIn('proposal', result)

    def test_deadline_interrupts_slow_provider_and_reports_korean(self):
        import nightly_learning as n
        import tempfile
        import time
        from unittest.mock import patch
        self.assertTrue(hasattr(n, 'MAX_SECONDS'), 'deadline missing')
        class Slow(FakeLLM):
            def generate(self, *args, **kwargs):
                time.sleep(1)
                return '遅い。'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text((ROOT / 'main.py').read_text())
            with patch.object(n, 'MAX_SECONDS', 0.05), patch.object(n, '_snapshot', return_value={'head': 'a' * 40, 'dirty': ''}):
                start = time.monotonic()
                result = n.run_nightly(project_root=root, llm=Slow())
                self.assertLess(time.monotonic() - start, 0.5)
            self.assertEqual(result['status'], 'incomplete')
            self.assertIn('동일 모델', n.format_report(result))
            self.assertIn('미완료', n.format_report(result))

    def test_active_lock_skips_immediately_and_crash_marker_prevents_rerun(self):
        import nightly_learning as n
        import tempfile
        import fcntl
        from datetime import datetime
        from zoneinfo import ZoneInfo
        self.assertTrue(hasattr(n, 'main'), 'CLI missing')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
            folder = root / 'scratch' / 'nightly_learning' / day
            folder.mkdir(parents=True)
            with (folder / 'run.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = n.run_nightly(project_root=root, llm=FakeLLM())
                self.assertEqual(result['status'], 'busy')
            (folder / 'started').write_text('interrupted')
            llm = FakeLLM()
            result = n.run_nightly(project_root=root, llm=llm)
            self.assertEqual(result['status'], 'incomplete')
            self.assertEqual(llm.calls, [])

    def test_cli_loads_only_project_env_and_prints_without_delivery(self):
        import nightly_learning as n
        from unittest.mock import patch
        self.assertTrue(hasattr(n, 'main'), 'CLI missing')
        with patch('dotenv.load_dotenv') as load, patch.object(n, 'run_nightly', return_value={'text': '야간 보고'}) as run, patch('builtins.print') as output:
            n.main()
            load.assert_called_once_with(n.ROOT / '.env', override=False)
            run.assert_called_once_with(project_root=n.ROOT)
            output.assert_called_once_with('야간 보고')

    def test_no_proposal_for_ties_regressions_dirty_or_changed_baseline(self):
        import nightly_learning as n
        import tempfile
        import json
        from unittest.mock import patch
        for mode in ('tie', 'regression', 'heldout-tie', 'dirty', 'changed', 'provider', 'identical'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                class Negative(FakeLLM):
                    def generate(self, prompt, *, instructions='', **kwargs):
                        if mode == 'provider':
                            raise RuntimeError('secret-must-not-appear')
                        if mode == 'identical' and not instructions.startswith(('LEARNER', 'JUDGE', 'OPTIMIZER')):
                            return 'はい。'
                        answer = super().generate(prompt, instructions=instructions, **kwargs)
                        if instructions.startswith('JUDGE'):
                            data, score = json.loads(prompt), json.loads(answer)
                            for label in ('A', 'B'):
                                if mode == 'tie' or (mode == 'heldout-tie' and data['scenario']['id'].startswith('heldout')):
                                    score[label] = {a: 3 for a in n.AXES}
                                if mode == 'regression' and '候補' in str(data[label]):
                                    score[label]['constraints'] = 2
                            return json.dumps(score)
                        return answer
                root = Path(directory)
                (root / 'main.py').write_text((ROOT / 'main.py').read_text())
                initial = {'head': 'a' * 40, 'dirty': ' M main.py' if mode == 'dirty' else ''}
                final = dict(initial, head='b' * 40) if mode == 'changed' else initial
                with patch.object(n, '_snapshot', side_effect=[initial, final]), patch('continuous_improvement.create_proposal') as create:
                    report = n.run_nightly(project_root=root, llm=Negative())
                    create.assert_not_called()
                self.assertNotIn('proposal', report)
                if mode in ('dirty', 'changed'):
                    self.assertEqual(report['status'], 'blocked')
                self.assertNotIn('secret-must-not-appear', json.dumps(report))
                self.assertLessEqual(len(report['text']), 3500)

    def test_failure_preserves_development_when_budget_summary_is_unavailable(self):
        import nightly_learning as n
        import tempfile
        from unittest.mock import patch
        class Broken(FakeLLM):
            def generate(self, prompt, *, instructions='', **kwargs):
                if instructions.startswith('OPTIMIZER'):
                    raise RuntimeError('secret')
                return super().generate(prompt, instructions=instructions, **kwargs)
            def summary(self):
                raise RuntimeError('secret')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'main.py').write_text((ROOT / 'main.py').read_text())
            with patch.object(n, '_snapshot', return_value={'head': 'a' * 40, 'dirty': ''}):
                report = n.run_nightly(project_root=root, llm=Broken())
            self.assertEqual(report['status'], 'incomplete')
            self.assertEqual(len(report['development']), 2)
            self.assertEqual(report['budget']['status'], 'unavailable')

    def test_paired_experiment_persists_and_proposes_exact_candidate(self):
        import nightly_learning as n
        self.assertTrue(hasattr(n, 'run_nightly'), 'runner missing')
        import tempfile
        import subprocess
        import shutil
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copy(ROOT / 'main.py', root / 'main.py')
            (root / '.gitignore').write_text('scratch/\n')
            for args in [('init', '-q'), ('add', '.'), ('-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'base')]:
                subprocess.run(['git', '-C', directory, *args], check=True)
            llm = FakeLLM()
            result = n.run_nightly(project_root=root, llm=llm)
            self.assertEqual(result['status'], 'proposed')
            self.assertEqual(len(result['comparisons']), 2)
            self.assertEqual(llm.optimizations, 1)
            optimizer_instructions = next(instructions for _, instructions in llm.calls
                                          if instructions.startswith('OPTIMIZER'))
            self.assertIn('Write all instruction prose in English.', optimizer_instructions)
            self.assertIn('Japanese is allowed only inside quoted examples.', optimizer_instructions)
            self.assertNotIn('heldout', llm.optimizer_input)
            for comparison in result['comparisons']:
                self.assertEqual([x['learner'] for x in comparison['baseline']],
                                 [x['learner'] for x in comparison['candidate']])
                self.assertEqual(len(comparison['baseline']), 2)
            proposal = result['proposal']
            self.assertEqual(proposal['baseline']['candidate_append'], result['candidate_append'])
            self.assertIn('evidence_sha256', proposal['baseline'])
            self.assertTrue(proposal['baseline']['tested_suffix'].endswith(result['candidate_append']))
            self.assertEqual(json.loads((root / 'scratch' / 'improvement' / 'proposals' / (proposal['id'] + '.json')).read_text()), proposal)
            self.assertLessEqual(len(result['text']), 3500)
            self.assertIn(proposal['approval_token'], result['text'])
            self.assertIn(result['candidate_append'], result['text'])
            count = len(llm.calls)
            self.assertEqual(n.run_nightly(project_root=root, llm=llm), result)
            self.assertEqual(len(llm.calls), count)
            persisted = root / 'scratch' / 'nightly_learning' / result['day'] / 'report.json'
            self.assertEqual(json.loads(persisted.read_text()), result)
            self.assertEqual(subprocess.check_output(['git', '-C', directory, 'status', '--porcelain']).decode(), '')


class FakeLLM:
    def __init__(self):
        self.calls = []
        self.optimizations = 0
        self.optimizer_input = ''

    def generate(self, prompt, *, instructions='', **kwargs):
        import json
        self.calls.append((prompt, instructions))
        if instructions.startswith('OPTIMIZER'):
            self.optimizations += 1
            self.optimizer_input = prompt
            return json.dumps({'append': 'Use a concrete, context-relevant follow-up question when natural.'})
        if instructions.startswith('JUDGE'):
            payload = json.loads(prompt)
            return json.dumps({label: {axis: (4 if '候補' in str(payload[label]) else 3)
                                      for axis in ('naturalness', 'relevance', 'level', 'constraints')}
                               for label in ('A', 'B')})
        if instructions.startswith('LEARNER'):
            return 'コーヒーをください。'
        return '候補です。' if 'Use a concrete' in instructions else 'はい。'

    def summary(self):
        return {'day': 'test', 'limit_usd': 1, 'charged_usd': 0, 'reserved_usd': 0, 'calls': len(self.calls)}


if __name__ == '__main__':
    unittest.main()
