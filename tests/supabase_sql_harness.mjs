// Run with: PGLITE_MODULE=/absolute/path/to/pglite/dist/index.js node tests/supabase_sql_harness.mjs
import assert from 'node:assert/strict';
import fs from 'node:fs';
const {PGlite} = await import(process.env.PGLITE_MODULE);
const db = new PGlite();
await db.exec(`create role anon; create role authenticated; create role service_role bypassrls;
create schema auth; create table auth.users(id uuid primary key);
create function auth.uid() returns uuid language sql stable as
$$ select nullif(current_setting('request.jwt.claim.sub', true),'')::uuid $$;
grant usage on schema auth to authenticated, anon;
grant execute on function auth.uid() to authenticated, anon;`);
await db.exec(fs.readFileSync('supabase/nihongo_chat_setup.sql','utf8'));
await db.exec(fs.readFileSync('supabase/003_message_order.sql','utf8'));
await db.exec(fs.readFileSync('supabase/003_message_order.sql','utf8'));
await db.exec(fs.readFileSync('supabase/002_app_functions.sql','utf8'));
// Idempotent additive migration.
await db.exec(fs.readFileSync('supabase/002_app_functions.sql','utf8'));
const a='11111111-1111-4111-8111-111111111111', b='22222222-2222-4222-8222-222222222222';
await db.query('insert into auth.users values ($1),($2)', [a,b]);
async function asUser(id) {
    await db.exec('reset role');
    await db.query("select set_config('request.jwt.claim.sub',$1,false)",[id]);
    await db.exec('set role authenticated');
}
await asUser(a);
await db.exec("insert into public.sessions(session_id,title,partner_name,difficulty,topic) values('s','Title','Yuki','beginner','free')");
const turn = `select public.save_chat_turn('u','a','s','hello','こんにちは',0.5) as result`;
assert.equal((await db.query(turn)).rows[0].result.created,true);
assert.equal((await db.query(turn)).rows[0].result.created,false);
assert.equal((await db.query('select count(*)::int as n from public.messages')).rows[0].n,2);
await assert.rejects(db.query("select public.save_chat_turn('u','a','s','changed','reply',0.5)"));
await asUser(b);
for (const table of ['sessions','messages','user_memories','session_summaries','user_facts','message_feedbacks','legacy_feedbacks']) {
    assert.equal((await db.query(`select * from public.${table}`)).rows.length,0);
}
assert.equal((await db.query("update public.messages set content='attack' returning id")).rows.length,0);
await assert.rejects(db.query("insert into public.messages(id,session_id,role,content) values('bad','s','user','bad')"));
await assert.rejects(db.query(`insert into public.user_facts(user_id,fact_key,fact_value) values('${a}','x','bad')`));
await asUser(a);
await db.exec("insert into public.user_memories(category,corrected_text) values('grammar','正しい')");
const memory=(await db.query('select * from public.practice_memories(3)')).rows[0];
assert.equal((await db.query('select public.review_memory($1,true) as ok',[memory.id])).rows[0].ok,true);
assert.equal((await db.query('select * from public.practice_memories(3)')).rows.length,0);
await asUser(b);
assert.equal((await db.query('select public.review_memory($1,true) as ok',[memory.id])).rows[0].ok,false);
for (let i=0;i<100;i++) assert.equal((await db.query('select public.consume_ai_usage() as ok')).rows[0].ok,true);
assert.equal((await db.query('select public.consume_ai_usage() as ok')).rows[0].ok,false);
await assert.rejects(db.query('update public.ai_usage set calls=0'));
await asUser(a);
assert.equal((await db.query('select public.consume_ai_usage() as ok')).rows[0].ok,true);
await db.exec('reset role; set role anon');
await assert.rejects(db.query('select * from public.messages'));
await assert.rejects(db.query('select public.consume_ai_usage()'));
if (process.env.IMPORT_SQL && process.env.IMPORT_OWNER) {
    await db.exec('reset role');
    await db.query('insert into auth.users values ($1)', [process.env.IMPORT_OWNER]);
    const sql = fs.readFileSync(process.env.IMPORT_SQL, 'utf8');
    await db.exec(sql);
    const counts = async () => (await db.query(`select
        (select count(*)::int from public.messages where user_id=$1) as messages,
        (select count(*)::int from public.legacy_feedbacks where user_id=$1) as archived`,
        [process.env.IMPORT_OWNER])).rows[0];
    const first = await counts();
    await db.exec(sql);
    assert.deepEqual(await counts(),first);
    console.log('PASS: private import and idempotent replay (no record contents logged)');
}
await db.close();
console.log('PASS: SQL migrations, replay, cross-account isolation, review scheduling, quota, anonymous denial');
