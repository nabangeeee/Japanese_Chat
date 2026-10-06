import io
import json
import unittest
from unittest.mock import Mock, patch
from automation.model_proxy import Proxy, MODEL

class RepairProxyTests(unittest.TestCase):
    def handler(self, body):
        data=json.dumps(body).encode()
        handler=object.__new__(Proxy)
        handler.path='/v1/chat/completions'
        handler.headers={'Content-Length':str(len(data))}
        handler.rfile=io.BytesIO(data)
        handler.reply=Mock()
        return handler

    def setUp(self):
        Proxy.charged=0
        Proxy.calls=0

    def test_foreign_model_never_reaches_provider(self):
        h=self.handler({'model':'expensive-model'})
        with patch('automation.model_proxy.httpx.post') as post:
            h.do_POST()
        post.assert_not_called()
        self.assertEqual(h.reply.call_args.args[0],400)

    def test_exhausted_budget_never_reaches_provider(self):
        Proxy.charged=1_000_000
        h=self.handler({'model':MODEL})
        with patch('automation.model_proxy.httpx.post') as post:
            h.do_POST()
        post.assert_not_called()
        self.assertEqual(h.reply.call_args.args[0],429)

    def test_limits_and_error_redaction(self):
        h=self.handler({'model':MODEL,'messages':[], 'max_completion_tokens':999999,'store':True})
        with patch.dict('os.environ',{'OPENAI_API_KEY':'private'}), patch('automation.model_proxy.httpx.post',return_value=Mock(status_code=401)) as post:
            h.do_POST()
        self.assertEqual(post.call_args.kwargs['json']['max_completion_tokens'],2048)
        self.assertFalse(post.call_args.kwargs['json']['store'])
        self.assertNotIn('private',str(h.reply.call_args))
        self.assertGreater(Proxy.charged,0)
