"""Bounded live self-play through the real FastAPI app, Supabase Auth and DB.

Runs the app in-process so the nightly job does not depend on a laptop web
server staying open. No provider, authentication or database mocks are used.
"""
import argparse
from contextlib import redirect_stdout
from datetime import datetime
import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TURNS = 3
MAX_SECONDS = 240


class CheckFailed(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise CheckFailed(message)


def checked(response, step):
    require(response.status_code == 200, f'{step}: HTTP {response.status_code}')
    return response.json()


def exercise(client, learner, *, email, password, owner, verify_remote, report):
    """All account identity checks happen before any synthetic records are made."""
    require(client.get('/api/sessions').status_code == 401, '로그인 없는 요청이 허용됨')
    checked(client.post('/api/auth/login', json={'email': email, 'password': password}), '로그인')
    identity = checked(client.get('/api/auth/me'), '계정 확인')
    require(identity['user_id'] == owner, '설정한 테스트 User UID와 로그인 계정이 다름')
    report['checks'].append('로그인·계정 확인·비로그인 차단')
    title = '[자동 검증] ' + datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    session = checked(client.post('/api/sessions', json={
        'title': title, 'partner_name': '유키', 'difficulty': 'beginner', 'topic': 'free',
    }), '테스트 대화방 생성')['session']
    session_id = session['session_id']
    report['session_id'] = session_id
    history = []
    for turn in range(TURNS):
        utterance = learner(history, turn)
        require(isinstance(utterance, str) and 0 < len(utterance.strip()) <= 500, '학습자 문장 형식 오류')
        body = {'message': utterance, 'request_id': str(uuid.uuid4()), 'session_id': session_id,
                'api_key': '', 'history': history, 'partner_name': '유키',
                'difficulty': 'beginner', 'topic': 'free'}
        reply = checked(client.post('/api/chat', json=body), f'대화 {turn + 1}')
        require(bool(reply.get('response')) and bool(reply.get('message_id')), '답변 또는 저장 ID 없음')
        history.extend([{'id': reply['user_message_id'], 'role': 'user', 'content': utterance},
                        {'id': reply['message_id'], 'role': 'assistant', 'content': reply['response']}])
        # Read the app's persisted state after each turn, never trust an echo alone.
        stored = checked(client.get('/api/sessions/' + session_id), '앱 기록 재조회')['messages']
        expected = [(m['id'], m['role'], m['content']) for m in history]
        actual = [(m['id'], m['role'], m['content']) for m in stored]
        require(actual == expected, '저장된 대화의 내용·순서가 일치하지 않음')
        report['turns'] = turn + 1
    report['checks'].append('실제 앱 AI 대화 3턴·메시지 6개 재조회')
    replay = checked(client.post('/api/chat', json=body), '전송 재시도')
    require(replay['message_id'] == reply['message_id'] and replay['response'] == reply['response'],
            '재전송이 기존 답변을 재사용하지 않음')
    verify_remote(client, owner, session_id, history)
    report['checks'].append('Supabase 직접 재조회·중복 방지·대화 요약 저장')
    checked(client.post('/api/auth/logout'), '로그아웃')
    require(client.get('/api/sessions').status_code == 401, '로그아웃 뒤 기록 접근 가능')
    report['checks'].append('로그아웃 차단')


def execute_live(report):
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    load_dotenv(ROOT / '.env.supabase')
    load_dotenv(ROOT / '.env.e2e', override=True)
    require(os.getenv('DATABASE_BACKEND') == 'supabase', 'Supabase 모드가 아님')
    names = ('NIHONGO_TEST_EMAIL', 'NIHONGO_TEST_PASSWORD', 'NIHONGO_TEST_USER_ID')
    require(all(os.getenv(name) for name in names), '.env.e2e 테스트 전용 계정 설정 필요')
    owner = str(uuid.UUID(os.environ['NIHONGO_TEST_USER_ID']))
    require(owner != '9369a1ee-efe5-4223-a66b-b6cb34cd2d09', '개인 계정 대신 테스트 전용 계정을 사용해야 함')
    require(bool(os.getenv('OPENAI_API_KEY')), 'OpenAI API 설정 필요')
    from fastapi.testclient import TestClient
    import httpx
    from main import app
    from llm_provider import experiment_meter
    from nightly_llm import BudgetedLLM
    import cloud_store

    meter = BudgetedLLM(ROOT, os.environ['OPENAI_API_KEY'])
    def learner(history, turn):
        return meter.generate(json.dumps({'history': history, 'turn': turn + 1}, ensure_ascii=False),
            instructions='Simulate a beginner Japanese learner talking about a walk in a park. '
            'Reply with exactly one short Japanese sentence under 100 characters. '
            'Include a small natural grammar mistake. Do not request tools or web searches.',
            max_output_tokens=256).strip()

    def verify_remote(client, owner, session_id, history):
        url, key = cloud_store.settings()
        token = client.cookies.get('nihongo_access_token')
        require(bool(token), '인증 쿠키 없음')
        headers = {'apikey': key, 'Authorization': 'Bearer ' + token}
        params = {'user_id': 'eq.' + owner, 'session_id': 'eq.' + session_id}
        with httpx.Client(timeout=20, headers=headers) as remote:
            rows = checked(remote.get(url + '/rest/v1/messages', params={**params,
                'select': 'id,role,content', 'order': 'timestamp.asc,sort_order.asc'}), 'Supabase 메시지 조회')
            require(rows == history, 'Supabase 메시지가 앱 대화와 다름')
            summaries = checked(remote.get(url + '/rest/v1/session_summaries',
                params={**params, 'select': 'summary_text'}), 'Supabase 요약 조회')
            require(len(summaries) == 1 and bool(summaries[0]['summary_text'].strip()), '대화 요약이 저장되지 않음')

    marker = experiment_meter.set(meter)
    try:
        with TestClient(app, base_url='https://nihongo-test.invalid', raise_server_exceptions=False) as client:
            exercise(client, learner, email=os.environ['NIHONGO_TEST_EMAIL'],
                     password=os.environ['NIHONGO_TEST_PASSWORD'], owner=owner,
                     verify_remote=verify_remote, report=report)
    finally:
        experiment_meter.reset(marker)
        report['budget'] = meter.summary()


def worker(path):
    report = {'status': 'failed', 'checks': [], 'turns': 0}
    try:
        # The app may log synthetic dialogue; do not send it to the cron report.
        with redirect_stdout(io.StringIO()):
            execute_live(report)
        report['status'] = 'passed'
    except CheckFailed as exc:
        report['failure'] = str(exc)
    except Exception as exc:
        # Never serialize credentials, provider response bodies, or HTTP headers.
        report['failure'] = type(exc).__name__
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2))


def run_report():
    day = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    folder = ROOT / 'scratch' / 'app_e2e' / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'report.json'
    with (folder / 'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status': 'busy', 'checks': []}
        if path.exists():
            prior = json.loads(path.read_text())
            if prior.get('status') == 'passed' or prior.get('session_id'):
                return prior
        try:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker', str(path)],
                           cwd=ROOT, timeout=MAX_SECONDS, check=True, capture_output=True)
        except subprocess.TimeoutExpired:
            # Prevent re-running interrupted paid work automatically that day.
            result = {'status': 'failed', 'checks': [], 'session_id': 'interrupted',
                      'failure': '240초 제한으로 중단. 다음 예약 실행 전에 점검 필요'}
            path.write_text(json.dumps(result, ensure_ascii=False))
        except subprocess.CalledProcessError:
            return {'status': 'failed', 'checks': [], 'failure': '테스트 프로세스 실행 실패'}
        return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=Path)
    args = parser.parse_args()
    if args.worker:
        worker(args.worker)
        return
    report = run_report()
    print('[니혼고챗 실제 앱 자동 검증] ' + report['status'])
    for check in report['checks']:
        print('확인: ' + check)
    if report.get('failure'):
        print('중단: ' + report['failure'])
    if report.get('budget'):
        print('야간 실험 공통 예산: ' + json.dumps(report['budget'], ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    sys.exit(main())
