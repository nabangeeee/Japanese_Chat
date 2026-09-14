import importlib.util
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace


class ProviderTests(unittest.TestCase):
    def test_search_citations_survive_as_safe_source_links(self):
        from llm_provider import generate_text
        annotation = SimpleNamespace(type='url_citation', url='https://example.com/a?q=1', title='source')
        with patch('llm_provider.OpenAI') as factory:
            factory.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status='completed', output_text='東京です。', output=[SimpleNamespace(type='message', content=[SimpleNamespace(type='output_text', annotations=[annotation])])])
            self.assertIn('[出典 1](https://example.com/a?q=1)', generate_text('key', 'news', web_search=True))

    def test_json_schema_contract(self):
        from llm_provider import generate_text
        with patch('llm_provider.OpenAI') as factory:
            call = factory.return_value.__enter__.return_value.responses.create
            call.return_value = SimpleNamespace(status='completed', output_text='{"items": []}')
            schema = {'type':'object','properties':{'items':{'type':'array','items':{'type':'string'}}}, 'required':['items'], 'additionalProperties':False}
            self.assertEqual(generate_text('key', 'words', json_schema=schema), '{"items": []}')
            self.assertEqual(call.call_args.kwargs['text']['format'], {'type':'json_schema', 'name':'result', 'schema':schema, 'strict':True})

    def test_text_contract(self):
        self.assertIsNotNone(importlib.util.find_spec('llm_provider'), 'Responses adapter is missing')
        from llm_provider import generate_text
        with patch('llm_provider.OpenAI') as factory:
            factory.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status='completed', output_text='こんにちは')
            self.assertEqual(generate_text('key', 'hello', instructions='Japanese', history=[{'role':'user','content':'hi'}, {'role':'assistant','content':'hello'}], web_search=True), 'こんにちは')
            kwargs = factory.return_value.__enter__.return_value.responses.create.call_args.kwargs
            self.assertEqual(kwargs['model'], 'gpt-6-astra')
            self.assertFalse(kwargs['store'])
            self.assertEqual(kwargs['instructions'], 'Japanese')
            self.assertEqual(kwargs['input'], [{'role':'user','content':'hi'}, {'role':'assistant','content':'hello'}, {'role':'user','content':'hello'}])
            self.assertEqual(kwargs['tools'], [{'type':'web_search'}])
            self.assertNotIn('temperature', kwargs)
            self.assertEqual(factory.call_args.kwargs['max_retries'], 0)
            self.assertGreater(factory.call_args.kwargs['timeout'], 0)

    def test_classified_retries_and_output_errors(self):
        import httpx
        from openai import APIConnectionError, APIStatusError
        from llm_provider import generate_text
        request = httpx.Request('POST', 'https://api.openai.com/v1/responses')
        for status, attempts in [(400, 1), (401, 1), (403, 1), (408, 3), (429, 3), (500, 3), (503, 3)]:
            with self.subTest(status=status), patch('llm_provider.OpenAI') as factory, patch('time.sleep'):
                call = factory.return_value.__enter__.return_value.responses.create
                error = APIStatusError('failure', response=httpx.Response(status, request=request), body=None)
                call.side_effect = error
                with self.assertRaises(APIStatusError):
                    generate_text('key', 'hi')
                self.assertEqual(call.call_count, attempts)
        with patch('llm_provider.OpenAI') as factory, patch('time.sleep') as sleep:
            call = factory.return_value.__enter__.return_value.responses.create
            call.side_effect = [APIConnectionError(request=request), SimpleNamespace(status='completed', output_text='OK')]
            self.assertEqual(generate_text('key', 'hi'), 'OK')
            sleep.assert_called_once_with(1.0)
        for status, text in [('incomplete', 'partial'), ('completed', '')]:
            with patch('llm_provider.OpenAI') as factory:
                factory.return_value.__enter__.return_value.responses.create.return_value = SimpleNamespace(status=status, output_text=text)
                with self.assertRaisesRegex(RuntimeError, 'OpenAI'):
                    generate_text('key', 'hi')
