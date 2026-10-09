"""In-memory Data API double for route tests. SQL/RLS are tested separately in PostgreSQL."""
from copy import deepcopy
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
from threading import RLock
from unittest.mock import patch
import cloud_store


@contextmanager
def cloud_fixture():
    tables = {name: [] for name in ('sessions', 'messages', 'user_memories', 'session_summaries', 'user_facts', 'message_feedbacks')}
    lock = RLock()
    def request(method, path, *, params=None, data=None, prefer=None):
        with lock:
            return deepcopy(handle(method, path, params or {}, data or {}))

    def handle(method, path, params, data):
        owner = cloud_store.owner()
        if path == 'rpc/consume_ai_usage':
            return True
        if path == 'rpc/save_chat_turn':
            s = data['p_session']
            if not any(r['session_id'] == s for r in tables['sessions']):
                raise ValueError('Missing session')
            u, a = data['p_user_message'], data['p_assistant_message']
            previous = cloud_store.get_saved_turn(u, a, s, data['p_user_text'])
            if previous:
                return {'content':previous['content'], 'created':False}
            if cloud_store.get_message(a):
                raise ValueError('Record conflict')
            cloud_store.save_message(u, s, 'user', data['p_user_text'])
            cloud_store.save_message(a, s, 'assistant', data['p_assistant_text'])
            return {'content':data['p_assistant_text'], 'created':True}
        if path == 'rpc/practice_memories':
            return [r for r in tables['user_memories'] if not r['next_review_at']][:data['p_limit']]
        if path == 'rpc/review_memory':
            for r in tables['user_memories']:
                if r['id'] == data['p_id']:
                    r['next_review_at'] = (datetime.now(timezone.utc) + timedelta(days=7 if data['p_remembered'] else 1)).isoformat()
                    r['review_count'] += 1
                    return True
            return False
        rows = tables[path]
        def matches(row):
            return row['user_id'] == owner and all(
                str(row.get(k)) == str(v)[3:] for k, v in params.items() if str(v).startswith('eq.')) and all(
                row.get(k) in json.loads('[' + v[4:-1] + ']')
                for k, v in params.items() if isinstance(v, str) and v.startswith('in.('))
        selected = [r for r in rows if matches(r)]
        if method == 'GET':
            order = params.get('order', '')
            if order:
                for part in reversed(order.split(',')):
                    field, direction = part.split('.')[:2]
                    selected.sort(key=lambda r: r.get(field) or '', reverse=direction == 'desc')
            offset = int(params.get('offset', 0))
            return selected[offset:offset + int(params.get('limit', 1000))]
        if method == 'POST':
            conflict = params.get('on_conflict')
            if conflict:
                keys = conflict.split(',')
                existing = next((r for r in rows if all(r.get(k) == data.get(k) for k in keys)), None)
                if existing is not None:
                    existing.update(data)
                    return [existing]
            row = {'id': len(rows) + 1, 'created_at': cloud_store.now(), 'updated_at': cloud_store.now(), **data}
            if path == 'user_memories':
                row.update(review_count=0, next_review_at=None)
            if path == 'messages':
                row = {'translation':None, 'furigana':None, 'sort_order':len(rows) + 1, **row}
            rows.append(row)
            return [row]
        if method == 'PATCH':
            for r in selected:
                r.update(data)
            return selected
        if method == 'DELETE':
            for r in selected:
                rows.remove(r)
                if path == 'sessions':
                    for child in ('messages', 'message_feedbacks', 'session_summaries'):
                        tables[child][:] = [c for c in tables[child] if c.get('session_id') != r['session_id']]
            return selected
        raise AssertionError((method, path))

    marker = cloud_store.identity.set({'id':'test-owner', 'token':'test-token'})
    try:
        with patch.object(cloud_store, 'request', side_effect=request), patch.object(cloud_store, 'settings', return_value=('https://example.supabase.co','sb_publishable_test')):
            yield tables
    finally:
        cloud_store.identity.reset(marker)
