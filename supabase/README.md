# Supabase 초기 설정

1. Supabase 프로젝트의 SQL Editor에서 New query를 엽니다.
2. `nihongo_chat_setup.sql`의 전체 내용을 복사해 붙여넣습니다.
3. Run을 한 번 누릅니다. 성공하면 Table Editor의 public 스키마에 테이블 6개가 생깁니다.

이 SQL은 새 프로젝트용입니다. 이미 같은 이름의 테이블이 있으면 전체 작업이
실패하며 기존 테이블을 덮어쓰지 않습니다. 성공 후 다시 실행할 필요가 없습니다.
실패한 편집기 세션이 transaction aborted 상태라면 `rollback;`을 먼저 실행합니다.

로그인한 사용자는 자기 user_id의 기록만 조회·추가·수정·삭제할 수 있습니다.
대화와 메시지, 메시지와 평가의 연결에도 소유자를 포함하여 다른 사용자의 기록에
연결하지 못하게 합니다. 로그아웃 상태인 anon에는 접근 권한을 주지 않습니다.
Supabase의 관리자와 service_role은 RLS를 우회하므로 앱의 사용자 요청에는
사용자 JWT를 사용해야 합니다. 관리자 키를 클라이언트에 넣으면 안 됩니다.

이 단계는 빈 테이블과 권한만 준비합니다. 현재 Python 앱은 여전히 SQLite를
사용합니다. 로그인, 사용자 JWT 검증, Supabase 연결, 사용량 제한은 별도 구현이
필요합니다. 현재 환경에 PostgreSQL 실행 도구가 없어 이 SQL을 실제 DB에서
실행하거나 계정 간 접근 차단을 검증하지는 못했습니다.

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

## 이전 파일 생성기 (준비 단계)

`export_sqlite.py --owner <Auth UID> --source-timezone Asia/Seoul`은 실행할 때마다
읽기 전용 원본에서 새 SQLite 백업을 만들고, 개인 기록이 포함된 SQL을 Git에서
제외된 `scratch/backups/`에 저장합니다. 시간대는 원본 앱의 실행 환경과 맞춰야 합니다.
대상 Auth 계정 존재 여부와 복사된 내용의 일치는 생성 SQL 실행 시 검사합니다.
기존의 같은 ID에 다른 내용이 있으면 덮어쓰지 않고 트랜잭션을 중단합니다.
숫자 sequence는 재실행해도 뒤로 돌아가지 않습니다.

현재 원본에서 메시지가 없는 평가 10개가 발견되어 파일 생성이 중단된 상태입니다.
원본 평가를 삭제하거나 건너뛰지 않습니다. 이 평가의 별도 보존 방식과 실제
Supabase 연결, 사용자 로그인 및 API 소유자 분리는 아직 구현해야 합니다.
이 준비 코드가 존재하는 것만으로 앱이 Supabase를 사용하는 것은 아닙니다.
