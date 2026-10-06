import unittest
from unittest.mock import patch
import httpx
from openai import RateLimitError
import llm_provider


class ProviderBillingTests(unittest.TestCase):
    def test_billing_failure_is_not_retried(self):
        for code in llm_provider.QUOTA_ERROR_CODES:
            with self.subTest(code=code):
                error = RateLimitError('quota', response=httpx.Response(429,
                    request=httpx.Request('POST', 'https://api.openai.com/v1/responses')),
                    body={'code': code, 'type': 'insufficient_quota'})
                with patch('llm_provider.OpenAI') as client, patch('llm_provider.time.sleep') as sleep, patch('cloud_store.consume_usage'):
                    create = client.return_value.__enter__.return_value.responses.create
                    create.side_effect = error
                    with self.assertRaises(RateLimitError):
                        llm_provider.generate_text('test', 'hello')
                    self.assertEqual(create.call_count, 1)
                    sleep.assert_not_called()
