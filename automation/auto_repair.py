"""One bounded hosted Hermes repair, followed by revision-aware deployment checks."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import httpx
import continuous_improvement as improvement

SITE = 'https://japanese-chat.onrender.com'


def daily_claim():
    if os.getenv('GITHUB_ACTIONS') != 'true' or os.getenv('NIHONGO_AUTO_REPAIR') != 'true':
        raise RuntimeError('Hosted automation must be explicitly enabled')
    if os.getenv('GITHUB_RUN_ATTEMPT') != '1':
        raise RuntimeError('Same-day retry is disabled')
    repo = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repo):
        raise RuntimeError('Invalid repository')
    day = datetime.now(ZoneInfo('Asia/Seoul')).date()
    with httpx.Client(headers={'Authorization':'Bearer '+os.environ['GH_TOKEN']}, timeout=20) as client:
        response = client.get(f'https://api.github.com/repos/{repo}/actions/workflows/auto-repair.yml/runs', params={'per_page':100})
        response.raise_for_status()
        runs = response.json()['workflow_runs']
    for run in runs:
        if str(run['id']) == os.environ['GITHUB_RUN_ID'] or run.get('conclusion') == 'skipped':
            continue
        date = datetime.fromisoformat(run['created_at'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Seoul')).date()
        if date == day:
            raise RuntimeError('An automatic attempt already exists for today')


def deployment_ready(sha, *, attempts=40, pause=15):
    for _ in range(attempts):
        try:
            with httpx.Client(timeout=20) as client:
                status = client.get(SITE+'/api/auth/status')
                home = client.get(SITE+'/')
                denied = client.get(SITE+'/api/sessions')
            if (status.status_code == 200 and status.json().get('revision') == sha
                    and status.json().get('enabled') is True and home.status_code == 200
                    and denied.status_code == 401):
                return True
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(pause)
    return False


def rollback(candidate):
    # Only revert our own single commit, and never rewrite somebody else's work.
    target = improvement._git_push_target(ROOT)
    if not target or improvement._git_head(ROOT) != candidate or not improvement._git_is_clean(ROOT):
        return None
    target_ref, remote_ref, remote_url = target
    remote = subprocess.check_output(['git','ls-remote','origin',remote_ref],cwd=ROOT,text=True).split()
    if not remote or remote[0] != candidate:
        return None
    subprocess.run(['git','-c','core.hooksPath=/dev/null','revert','--no-edit',candidate],cwd=ROOT,check=True)
    reverted = improvement._git_head(ROOT)
    ok, _ = improvement._push_verified_commit(ROOT,reverted,candidate,target_ref,remote_ref,remote_url)
    return reverted if ok else None


def main():
    daily_claim()
    baseline = improvement._git_head(ROOT)
    if not baseline or not deployment_ready(baseline,attempts=2,pause=5):
        raise RuntimeError('Current deployment is not healthy or does not match main')
    workspace = improvement._create_worktree(ROOT,baseline)
    if not workspace:
        raise RuntimeError('Could not create preflight clone')
    try:
        if not improvement._verify_project(workspace):
            raise RuntimeError('Baseline tests failed; automatic changes are blocked')
    finally:
        improvement._remove_worktree(ROOT,workspace)
    signal = improvement.ImprovementSignal('automatic_small_fix','문자열 표시 오류 자동 점검',
        'Inspect existing deterministic tests and formatting code. Find a concrete reproducible bug; if none, make no edits. '
        'Only clean_japanese_text, clean_translation_text or simple static/style.css changes are authorized. '
        'Add a new tests/test_auto_*.py regression test. Never modify existing tests, auth, storage, prompts, dependencies or automation.',
        ['Reproduce the bug with a deterministic regression test', 'Preserve all existing tests', 'Pass the complete suite'], {})
    proposal = improvement.create_proposal(signal,state_dir=ROOT/'scratch/improvement',project_root=ROOT,notify=False)
    success = improvement.approve_proposal(proposal['id'],proposal['approval_token'],project_root=ROOT,
        notify=False,timeout_seconds=300,automatic=True,approval_source='standing-small-fix-policy')
    if not success:
        raise RuntimeError('No verified eligible patch was published; inspect the proposal report')
    candidate = improvement._git_head(ROOT)
    if deployment_ready(candidate):
        print('Verified patch published and deployed: '+candidate)
        return
    reverted = rollback(candidate)
    if reverted and deployment_ready(reverted):
        raise RuntimeError('Deployment check failed; previous code restored by a revert commit')
    raise RuntimeError('Deployment check failed; automatic recovery not confirmed. Manual action required')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Do not leak remote URLs containing credentials or HTTP request bodies.
        print(str(exc) if type(exc) is RuntimeError else type(exc).__name__)
        sys.exit(1)
