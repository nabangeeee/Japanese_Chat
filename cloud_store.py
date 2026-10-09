"""Supabase Data API using the verified user's JWT, never an administrator key."""
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
import httpx
from fastapi import HTTPException

identity = ContextVar('supabase_identity', default=None)


def settings():
    url = os.getenv('SUPABASE_URL', '').rstrip('/')
    key = os.getenv('SUPABASE_PUBLISHABLE_KEY', '')
    if not url.startswith('https://') or not key.startswith('sb_publishable_'):
        raise RuntimeError('Set SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY')
    return url, key


def request(method, path, *, params=None, data=None, prefer=None):
    user = identity.get()
    if not user:
        raise HTTPException(401, '로그인이 필요합니다.')
    url, key = settings()
    headers = {'apikey': key, 'Authorization': 'Bearer ' + user['token']}
    if prefer:
        headers['Prefer'] = prefer
    try:
        client = user.get('http_client')
        send = client.request if client is not None else httpx.request
        response = send(method, url + '/rest/v1/' + path, params=params,
                                 json=data, headers=headers, timeout=20)
    except httpx.HTTPError:
        raise HTTPException(503, '기록 저장소에 연결하지 못했습니다.') from None
    if response.is_error:
        try:
            error_code = response.json().get('code')
        except (ValueError, AttributeError):
            error_code = None
        if error_code == '42703':
            raise HTTPException(503, 'DB 업데이트가 필요합니다. 운영자가 Supabase의 추가 SQL 적용 상태를 확인해 주세요.')
        if response.status_code == 401:
            raise HTTPException(401, '다시 로그인해 주세요.')
        if response.status_code == 409:
            raise ValueError('Record conflict')
        raise HTTPException(503, '기록 저장소 요청에 실패했습니다. DB 설정을 확인해 주세요.')
    return response.json() if response.content else None


def owner():
    if not identity.get():
        raise HTTPException(401, '로그인이 필요합니다.')
    return identity.get()['id']


def select(table, **filters):
    return request('GET', table, params={'user_id': 'eq.' + owner(), **filters})


def insert(table, values, conflict=None):
    values = {**values, 'user_id': owner()}
    return request('POST', table, data=values,
                   params={'on_conflict': conflict} if conflict else None,
                   prefer='return=representation' + (',resolution=merge-duplicates' if conflict else ''))[0]


def update(table, values, **filters):
    return request('PATCH', table, data=values,
                   params={'user_id': 'eq.' + owner(), **filters}, prefer='return=representation')


def now():
    return datetime.now(timezone.utc).isoformat()


def init_db():
    settings()


def create_session(session_id, title, partner_name, difficulty, topic, roleplay_id=None, roleplay_args=None):
    return insert('sessions', dict(session_id=session_id, title=title, partner_name=partner_name,
                  difficulty=difficulty, topic=topic, roleplay_id=roleplay_id, roleplay_args=roleplay_args or {}))


def get_all_sessions():
    return select('sessions', order='updated_at.desc', limit=1000)


def get_session(session_id):
    rows = select('sessions', session_id='eq.' + session_id)
    return rows[0] if rows else None


def delete_session(session_id):
    return bool(request('DELETE', 'sessions', params={'user_id': 'eq.' + owner(),
                        'session_id': 'eq.' + session_id}, prefer='return=representation'))


def update_session_timestamp(session_id):
    update('sessions', {'updated_at': now()}, session_id='eq.' + session_id)


def get_message(message_id):
    rows = select('messages', id='eq.' + message_id)
    return rows[0] if rows else None


def get_session_messages(session_id):
    rows = []
    while True:
        page = select('messages', session_id='eq.' + session_id,
                      order='timestamp.asc,sort_order.asc', limit=500, offset=len(rows))
        rows.extend(page)
        if len(page) < 500:
            break
    feedback = {f['message_id']: f for f in select('message_feedbacks', session_id='eq.' + session_id)}
    for row in rows:
        if row['id'] in feedback:
            row['feedback_rating'] = feedback[row['id']]['rating']
            row['feedback_text'] = feedback[row['id']]['feedback_text']
    return rows


def save_message(msg_id, session_id, role, content, translation=None, furigana=None, response_time_sec=None, timestamp=None):
    return insert('messages', dict(id=msg_id, session_id=session_id, role=role, content=content,
                  translation=translation, furigana=furigana, response_time_sec=response_time_sec,
                  timestamp=timestamp or now()))


def update_message_quality_score(msg_id, score):
    update('messages', {'quality_score': score}, id='eq.' + msg_id)


def save_message_detail(message_id, field, value):
    if field not in ('translation', 'furigana'):
        raise ValueError('Unsupported detail')
    return bool(update('messages', {field: value}, id='eq.' + message_id, role='eq.assistant'))


def save_user_memory(category, original_text, corrected_text, explanation):
    return insert('user_memories', dict(category=category, original_text=original_text,
                  corrected_text=corrected_text, explanation=explanation))


def get_user_memories(limit=20):
    return select('user_memories', order='created_at.desc', limit=limit)


def save_session_summary(session_id, summary_text):
    insert('session_summaries', dict(session_id=session_id, summary_text=summary_text,
           updated_at=now()), 'user_id,session_id')


def get_session_summary(session_id):
    rows = select('session_summaries', session_id='eq.' + session_id)
    return rows[0]['summary_text'] if rows else None


def get_session_summaries(session_ids):
    """Fetch only the displayed sessions, in bounded batches instead of N reads."""
    summaries = {}
    for start in range(0, len(session_ids), 100):
        batch = session_ids[start:start + 100]
        rows = select('session_summaries',
                      session_id='in.(' + ','.join(json.dumps(s) for s in batch) + ')',
                      select='session_id,summary_text', limit=len(batch))
        summaries.update((row['session_id'], row['summary_text']) for row in rows)
    return summaries


def save_user_fact(fact_key, fact_value):
    insert('user_facts', dict(fact_key=fact_key, fact_value=fact_value, updated_at=now()), 'user_id,fact_key')


def get_all_user_facts():
    return select('user_facts', order='updated_at.desc')


def save_message_feedback(message_id, session_id, rating, feedback_text=None):
    msg = get_message(message_id)
    if rating not in (-1, 1) or not msg or msg['role'] != 'assistant':
        raise ValueError('Invalid feedback target')
    if session_id is not None and session_id != msg['session_id']:
        raise ValueError('Invalid session')
    return insert('message_feedbacks', dict(message_id=message_id, session_id=msg['session_id'],
                  rating=rating, feedback_text=feedback_text, created_at=now()), 'user_id,message_id')


def get_negative_feedbacks(limit=10):
    return select('message_feedbacks', rating='eq.-1', order='created_at.desc', limit=limit)


def get_saved_turn(user_id, assistant_id, session_id, content):
    user = get_message(user_id)
    if not user:
        return None
    assistant = get_message(assistant_id)
    if (user['session_id'] != session_id or user['role'] != 'user' or user['content'] != content
            or not assistant or assistant['session_id'] != session_id or assistant['role'] != 'assistant'):
        raise ValueError('Request ID conflict')
    return assistant


def save_chat_turn(user_id, assistant_id, session_id, user_text, assistant_text, elapsed):
    result = request('POST', 'rpc/save_chat_turn', data=dict(p_user_message=user_id,
                     p_assistant_message=assistant_id, p_session=session_id,
                     p_user_text=user_text, p_assistant_text=assistant_text, p_elapsed=elapsed))
    return result['content'], result['created']


def get_practice_memories(limit=3):
    return request('POST', 'rpc/practice_memories', data={'p_limit': limit})


def record_memory_review(memory_id, remembered):
    return request('POST', 'rpc/review_memory', data={'p_id': memory_id, 'p_remembered': remembered})


def consume_usage():
    if not request('POST', 'rpc/consume_ai_usage', data={}):
        raise HTTPException(429, '오늘의 AI 사용량을 모두 사용했어요. 내일 다시 만나요.')
