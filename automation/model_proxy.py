"""Credential proxy: one fixed model, bounded calls and conservative run budget."""
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
import httpx

MODEL = 'gpt-4.1-mini'
# Conservative rates above the documented GPT-4.1 mini text pricing.
# The provider project's own spend limits remain authoritative for billing.
MAX_MICRO_USD = 1_000_000

class Proxy(BaseHTTPRequestHandler):
    charged = 0
    calls = 0

    def log_message(self, *_):
        pass

    def reply(self, code, obj):
        payload = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path != '/v1/models':
            return self.reply(404, {'error':'Unsupported route'})
        self.reply(200, {'object':'list','data':[{'id':MODEL,'object':'model'}]})

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/v1/chat/completions' or not 0 < length <= 64000:
                return self.reply(400, {'error':'Unsupported request'})
            body = json.loads(self.rfile.read(length))
            if body.get('model') != MODEL:
                return self.reply(400, {'error':'Model or streaming not permitted'})
            # Charge the upper reservation, including failed upstream calls.
            reserve = (length + 1024) * 1 + 2048 * 4
            if Proxy.calls >= 12 or Proxy.charged + reserve > MAX_MICRO_USD:
                return self.reply(429, {'error':'Automatic repair budget exhausted'})
            allowed = {'messages','tools','tool_choice','parallel_tool_calls'}
            request = {key:body[key] for key in allowed if key in body}
            request.update(model=MODEL, max_completion_tokens=2048, store=False)
            Proxy.calls += 1
            Proxy.charged += reserve
            response = httpx.post('https://api.openai.com/v1/chat/completions',
                headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},json=request, timeout=90)
            if response.status_code != 200:
                return self.reply(response.status_code, {'error':'Upstream model request failed'})
            result = response.json()
            if body.get('stream'):
                choices = []
                for choice in result['choices']:
                    delta = dict(choice['message'])
                    if delta.get('tool_calls'):
                        delta['tool_calls'] = [dict(call, index=i) for i, call in enumerate(delta['tool_calls'])]
                    choices.append({'index':choice['index'], 'delta':delta, 'finish_reason':choice['finish_reason']})
                chunk = {'id':result['id'], 'object':'chat.completion.chunk', 'created':result['created'], 'model':MODEL, 'choices':choices}
                payload = ('data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n').encode()
                self.send_response(200)
                self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            else:
                self.reply(200, result)
        except Exception:
            self.reply(502, {'error':'Model proxy failed'})

if __name__ == '__main__':
    HTTPServer(('127.0.0.1',8645),Proxy).serve_forever()
