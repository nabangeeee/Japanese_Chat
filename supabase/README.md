# Supabase 초기 설정

1. Supabase 프로젝트의 SQL Editor에서 New query를 엽니다.
2. `nihongo_chat_setup.sql`의 전체 내용을 복사해 붙여넣습니다.
3. Run을 한 번 누릅니다. 성공하면 Table Editor의 public 스키마에 테이블 6개가 생깁니다.
4. `002_app_functions.sql`을 실행합니다. 이미 적용한 초기 버전에 메시지 순서 열이
   없다면 `003_message_order.sql`도 실행합니다. 두 추가 파일은 재실행할 수 있습니다.

이 SQL은 새 프로젝트용입니다. 이미 같은 이름의 테이블이 있으면 전체 작업이
실패하며 기존 테이블을 덮어쓰지 않습니다. 성공 후 다시 실행할 필요가 없습니다.
실패한 편집기 세션이 transaction aborted 상태라면 `rollback;`을 먼저 실행합니다.

로그인한 사용자는 자기 user_id의 기록만 조회·추가·수정·삭제할 수 있습니다.
대화와 메시지, 메시지와 평가의 연결에도 소유자를 포함하여 다른 사용자의 기록에
연결하지 못하게 합니다. 로그아웃 상태인 anon에는 접근 권한을 주지 않습니다.
Supabase의 관리자와 service_role은 RLS를 우회하므로 앱의 사용자 요청에는
사용자 JWT를 사용해야 합니다. 관리자 키를 클라이언트에 넣으면 안 됩니다.

앱은 `DATABASE_BACKEND=supabase`일 때 Supabase Auth와 Data API를 사용합니다.
`.env.supabase` 또는 배포 환경에 `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY`를
설정하세요. 공개 키는 `sb_publishable_` 형식입니다. 사용자 토큰은 HttpOnly 쿠키로
관리하고 요청마다 Auth 서버에서 검증합니다. 기록 조회·저장에는 그 사용자의 JWT를
전달하므로 RLS가 적용됩니다. 연결 실패 시 SQLite로 우회하지 않습니다.
SQLite 모드는 기존 로컬 도구·백업·단위 테스트를 위해 남겨 두었습니다.
외부 배포 시 반드시 Supabase 모드를 설정하세요.

AI 사용량은 계정별 하루 100회 API 시도로 제한합니다(한국 시간 기준).
답변 외에 번역, 후리가나, 요약, 품질 평가, 문법 분석, 재시도도 포함됩니다.
이는 대화 100턴을 뜻하지 않습니다. 기존 SQLite를 직접 읽는 아침 학습 요약과
밤 9시 품질 관찰 작업은 아직 Supabase의 새 기록을 읽지 않습니다.

## 다음 기록 이전 작업에서 지킬 사항

- 기존 SQLite를 백업하고, 확인된 본인 Auth UID에만 모든 기존 기록을 배정합니다.
- 기존 문자열/숫자 ID와 참조 관계를 유지합니다. 삽입·upsert의 충돌 키에는 user_id를 포함합니다.
- SQLite의 시간대 없는 기존 시간은 원래 기록한 시간대를 확인하여 timestamptz로 변환합니다.
- roleplay_args의 JSON 문자열은 JSON 객체로 변환합니다.
- 기존 숫자 ID를 삽입한 후 세 identity sequence를 각각 max(id) 이후로 조정합니다.
- 원본의 고아 메시지·평가가 있으면 보고하고 해결합니다. 무시하거나 삭제하지 않습니다.
- 기록 수·내용·관계를 대조하고, 두 테스트 계정으로 타인 기록 조회/수정 및
  타인 대화 연결이 차단되는지 검증한 다음 앱을 전환합니다.

공식 문서: https://supabase.com/docs/guides/database/postgres/row-level-security

## 이전 파일 생성기

`export_sqlite.py --owner <Auth UID> --source-timezone Asia/Seoul`은 실행할 때마다
읽기 전용 원본에서 새 SQLite 백업을 만들고, 개인 기록이 포함된 SQL을 Git에서
제외된 `scratch/backups/`에 저장합니다. 시간대는 원본 앱의 실행 환경과 맞춰야 합니다.
대상 Auth 계정 존재 여부와 복사된 내용의 일치는 생성 SQL 실행 시 검사합니다.
기존의 같은 ID에 다른 내용이 있으면 덮어쓰지 않고 트랜잭션을 중단합니다.
숫자 sequence는 재실행해도 뒤로 돌아가지 않습니다.

원본 메시지와 연결할 수 없는 평가는 `legacy_feedbacks`에 원래 ID·내용·날짜를
보존합니다. 정상 평가는 `message_feedbacks`로 옮깁니다. 개인 기록과 이전 SQL은
GitHub에 올리지 않습니다.

## 실제 앱 자동 검증

테스트 전용 Supabase Auth 사용자를 만들고 `.env.e2e`에 다음 값을 직접 입력합니다.
이 파일은 Git에서 제외됩니다. 개인 기록을 이전한 계정은 테스트에 사용할 수 없습니다.

```
NIHONGO_TEST_EMAIL=테스트 계정 이메일
NIHONGO_TEST_PASSWORD=테스트 계정 비밀번호
NIHONGO_TEST_USER_ID=테스트 계정 UID
```

`.venv/bin/python app_e2e.py`를 실행하면 실제 FastAPI 앱을 프로세스 내부에서 구동해
로그인, 비로그인 거부, AI 학습자와 튜터의 3턴 대화, 6개 메시지 재조회, 중복 전송,
Supabase 직접 조회, 대화 요약 저장, 로그아웃 차단을 검사합니다. 인증·DB·AI는
실제 서비스를 사용합니다. 브라우저 렌더링과 배포 서버의 네트워크 설정 검사는
포함하지 않습니다. 테스트 대화는 전용 계정에 남겨 확인할 수 있습니다.

밤 10시 기존 Hermes 작업도 이 검사를 먼저 실행한 뒤 합성 품질 실험을 실행합니다.
두 작업은 기존의 하루 $1 예산 기록을 공유합니다. 각 앱 검증은 최대 240초이며,
당일 완료/대화 생성 후 실패한 검증은 자동 반복하지 않습니다. 설정 누락은 설정 후
다시 실행할 수 있습니다. 보고서는 `scratch/app_e2e/YYYY-MM-DD/report.json`입니다.
