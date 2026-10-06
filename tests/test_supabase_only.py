import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import cloud_store

ROOT = Path(__file__).resolve().parents[1]

class SupabaseOnlyTests(unittest.TestCase):
    def test_missing_cloud_settings_refuse_startup(self):
        with patch.dict(os.environ, {'SUPABASE_URL':'', 'SUPABASE_PUBLISHABLE_KEY':''}):
            with self.assertRaises(RuntimeError):
                cloud_store.init_db()

    def test_runtime_modules_do_not_import_sqlite_or_old_database(self):
        for name in ('main.py','cloud_store.py','memory_retrieval.py','morning_digest.py','continuous_improvement.py'):
            tree = ast.parse((ROOT/name).read_text())
            imports = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.extend(item.name for item in node.names)
                elif isinstance(node, ast.ImportFrom):
                    imports.append(node.module)
            self.assertNotIn('sqlite3', imports, name)
            self.assertNotIn('database', imports, name)

    def test_scheduled_generation_has_explicit_separate_usage_scope(self):
        from llm_provider import generate_text
        with patch('llm_provider.OpenAI') as client, patch('cloud_store.consume_usage') as quota:
            client.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status='completed', output_text='hello')
            generate_text('test', 'prompt', account_usage=False)
            quota.assert_not_called()
            generate_text('test', 'prompt')
            quota.assert_called_once()
