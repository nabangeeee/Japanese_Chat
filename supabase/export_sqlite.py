"""Create a private, atomic SQL Editor import from a consistent SQLite backup."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

TABLES = ('sessions', 'messages', 'user_memories', 'session_summaries',
          'user_facts', 'message_feedbacks')
TIMES = {'created_at', 'updated_at', 'timestamp', 'next_review_at'}


def literal(value):
    # Standard strings with standard_conforming_strings enabled below.
    return "'" + value.replace("'", "''") + "'"


def build_sql(records, owner):
    owner = str(UUID(owner))
    statements = [
        '-- 개인 기록 포함: 공개하거나 GitHub에 올리지 마세요.',
        'begin;', 'set local standard_conforming_strings = on;',
        "do $$ begin if not exists (select 1 from auth.users where id = "
        + literal(owner) + "::uuid) then raise exception 'Owner UID not found'; end if; end $$;",
        'lock table ' + ', '.join('public.' + t for t in TABLES) + ' in share row exclusive mode;',
    ]
    for table in TABLES:
        rows = records[table]
        payload = literal(json.dumps(rows, ensure_ascii=False, allow_nan=False))
        statements += [
            f'create temporary table import_{table} on commit drop as '
            f'select * from jsonb_populate_recordset(null::public.{table}, {payload}::jsonb);',
            f'insert into public.{table} select * from import_{table} on conflict do nothing;',
            'do $$ begin if exists ('
            f'select * from import_{table} except select * from public.{table}'
            f") then raise exception 'Import mismatch: {table}'; end if; end $$;",
        ]
    for table in ('user_memories', 'user_facts', 'message_feedbacks'):
        # Never rewind sequences, including on repeat imports.
        statements.append(
            f"select setval('public.{table}_id_seq', greatest("
            f"(select last_value from public.{table}_id_seq), "
            f"coalesce((select max(id) from public.{table}), 1)), true);"
        )
    statements += ['commit;', 'select ' + literal(owner) + '::uuid as imported_owner;']
    return '\n\n'.join(statements) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True, type=UUID)
    parser.add_argument('--source-timezone', required=True,
                        help='Timezone of naive timestamps written by the original app')
    args = parser.parse_args()
    zone = ZoneInfo(args.source_timezone)
    root = Path(__file__).resolve().parents[1]
    folder = root / 'scratch' / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d-%H%M%S-%f')
    backup = folder / f'before-supabase-{stamp}.db'
    output = folder / f'supabase-import-{stamp}.sql'
    fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    source = sqlite3.connect((root / 'nihongo_chat.db').as_uri() + '?mode=ro', uri=True)
    dest = sqlite3.connect(backup)
    try:
        source.backup(dest)
        assert dest.execute('pragma integrity_check').fetchall() == [('ok',)]
        dest.row_factory = sqlite3.Row
        records = {}
        for table in TABLES:
            rows = []
            for row in dest.execute(f'SELECT * FROM {table}'):
                item = dict(row)
                item['user_id'] = str(args.owner)
                for name in TIMES & item.keys():
                    if item[name] is not None:
                        dt = datetime.fromisoformat(item[name])
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=zone)
                        item[name] = dt.isoformat()
                if 'roleplay_args' in item:
                    item['roleplay_args'] = json.loads(item['roleplay_args'])
                rows.append(item)
            records[table] = rows
        sessions = {r['session_id'] for r in records['sessions']}
        messages = {r['id']: r for r in records['messages']}
        for row in records['messages'] + records['session_summaries']:
            if row['session_id'] not in sessions:
                raise ValueError('Orphan session reference: import stopped')
        for row in records['message_feedbacks']:
            msg = messages.get(row['message_id'])
            if msg is None or row['session_id'] not in (None, msg['session_id']):
                raise ValueError('Orphan or mismatched feedback: import stopped')
        sql = build_sql(records, str(args.owner))
        fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(sql)
        print('Backup:', backup)
        print('Import SQL:', output)
        print('Row counts:', {t: len(rows) for t, rows in records.items()})
    finally:
        dest.close()
        source.close()


if __name__ == '__main__':
    main()
