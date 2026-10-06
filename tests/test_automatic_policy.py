import subprocess
import tempfile
from pathlib import Path
import unittest
from automation.policy import allowed_candidate

class AutomaticPolicyTests(unittest.TestCase):
    def setUp(self):
        folder = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(folder)
        (self.root/'tests').mkdir()
        (self.root/'main.py').write_text('import re\ndef clean_japanese_text(text: str) -> str:\n    return text\n')
        (self.root/'tests/test_existing.py').write_text('# trusted tests\n')
        self.git('init','-q')
        self.git('config','user.email','test@example.com')
        self.git('config','user.name','Test')
        self.git('add','.')
        self.git('commit','-qm','baseline')
        self.base = self.git('rev-parse','HEAD').strip()
        (self.root/'tests/test_auto_format.py').write_text('import unittest\n')

    def git(self,*args):
        return subprocess.check_output(['git',*args],cwd=self.root,text=True)

    def change(self, body):
        (self.root/'main.py').write_text('import re\ndef clean_japanese_text(text: str) -> str:\n    '+body+'\n')

    def test_small_pure_formatter_change_is_allowed(self):
        self.change('return text.strip()')
        self.assertTrue(allowed_candidate(self.root,self.base))

    def test_sensitive_files_and_existing_tests_are_blocked(self):
        self.change('return text.strip()')
        for name in ('cloud_auth.py','scheduled_store.py','tests/test_existing.py'):
            p=self.root/name
            old=p.read_text() if p.exists() else None
            p.write_text('# changed\n')
            self.assertFalse(allowed_candidate(self.root,self.base))
            if old is None: p.unlink()
            else: p.write_text(old)

    def test_impure_formatter_changes_are_blocked(self):
        for body in ('return open("secret").read()', 're.cache = {}\n    return text', 'return text.__class__', 'import os\n    return text'):
            self.change(body)
            self.assertFalse(allowed_candidate(self.root,self.base),body)

    def test_regression_test_is_required(self):
        self.change('return text.strip()')
        (self.root/'tests/test_auto_format.py').unlink()
        self.assertFalse(allowed_candidate(self.root,self.base))
