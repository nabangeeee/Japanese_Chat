const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function setup() {
    const elements = new Map();
    const element = () => {
        const classes = new Set();
        return { value: '', style: {}, innerHTML: '', textContent: '',
            classList: { add: x => classes.add(x), remove: x => classes.delete(x),
                contains: x => classes.has(x), toggle: (x, yes) => yes ? classes.add(x) : classes.delete(x) },
            remove() {}, appendChild() {} };
    };
    const get = id => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
    const local = new Map();
    const active = new Map();
    const requests = [];
    const warnings = [];
    const env = { failCache: false, reply: async () => ({ ok: true, json: async () => ({ response: 'reply', message_id: 'assistant-db', user_message_id: 'user-db' }) }) };
    const storage = map => ({ setItem(key, value) {
        if (env.failCache) throw new Error('QuotaExceededError');
        map.set(key, value);
    }, removeItem: key => map.delete(key), getItem: key => map.get(key) });
    const context = vm.createContext({
        console: { log() {}, error() {} }, alert: x => warnings.push(x), confirm: () => true,
        setTimeout() {}, document: { getElementById: get, createElement: element, addEventListener() {},
            querySelectorAll: () => [], querySelector: () => null },
        localStorage: storage(local), sessionStorage: storage(active),
        fetch: async (url, options = {}) => {
            const request = { url, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null };
            requests.push(request);
            return env.reply(request);
        }
    });
    vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
    const run = code => vm.runInContext(code, context);
    run(`escapeHTML = value => String(value); state.currentSessionId = 'old-session';`);
    return { run, get, local, active, requests, warnings, env };
}

const tests = {
    async feedbackIds() {
        const h = setup();
        h.get('messageInput').value = 'hello';
        await h.run('sendMessage()');
        assert.equal(h.run('state.messages[0].id'), 'user-db');
        assert.equal(h.run('state.messages[1].id'), 'assistant-db');
        assert.match(h.get('messages').innerHTML, /submitFeedback\(event, 'assistant-db'/);
        await h.run('submitFeedback(null, "assistant-db", 1)');
        assert.equal(h.requests.at(-1).body.message_id, 'assistant-db');
        assert.equal(h.run('state.messages[1].feedback_rating'), 1);
        assert.match(h.get('messages').innerHTML, /like-btn active/);
        for (const fail of ['http', 'network']) {
            h.env.reply = async () => { if (fail === 'network') throw new Error('offline'); return { ok: false, status: 404 }; };
            await h.run('submitFeedback(null, "assistant-db", -1)');
            assert.equal(h.run('state.messages[1].feedback_rating'), 1);
            assert.match(h.get('messages').innerHTML, /like-btn active/);
            assert.doesNotMatch(h.get('messages').innerHTML, /dislike-btn active/);
            assert.match(h.warnings.at(-1), /피드백.*다시/);
        }
        h.run('addWelcomeMessage()');
        assert.doesNotMatch(h.get('messages').innerHTML, /submitFeedback/);
        const before = h.requests.length;
        await h.run('submitFeedback(null, state.messages[0].id, 1)');
        await h.run('submitFeedback(null, "unknown", 1)');
        assert.equal(h.requests.length, before, 'Local or missing messages cannot receive feedback');
        h.env.reply = async () => ({ ok: true, json: async () => ({ response: 'legacy reply' }) });
        h.get('messageInput').value = 'again';
        await h.run('sendMessage()');
        assert.doesNotMatch(h.get('messages').innerHTML, /submitFeedback/);
        assert.equal(h.run('state.messages.at(-1).id'), undefined, 'Never invent a persisted assistant ID');
    },
    async feedbackPending() {
        for (const outcome of ['success', 'http', 'network']) {
            const h = setup();
            h.run(`state.messages = [{id: 'msg', role: 'assistant', content: 'hello'}]; renderMessages();`);
            let release;
            let serverRating;
            h.env.reply = request => new Promise((resolve, reject) => {
                release = () => {
                    if (outcome === 'network') return reject(new Error('offline'));
                    if (outcome === 'success') serverRating = request.body.rating;
                    resolve({ ok: outcome === 'success', status: 503 });
                };
            });
            const first = h.run('submitFeedback(null, "msg", 1)');
            const duplicate = h.run('submitFeedback(null, "msg", -1)');
            // Check before awaiting: an unresolved duplicate must not hide a failure.
            assert.equal(h.requests.length, 1, 'Same-message feedback cannot overlap');
            assert.match(h.get('messages').innerHTML, /like-btn[^>]*disabled/);
            assert.match(h.get('messages').innerHTML, /dislike-btn[^>]*disabled/);
            release();
            await Promise.all([first, duplicate]);
            assert.equal(h.run('state.messages[0].feedback_rating'), serverRating);
            assert.doesNotMatch(h.get('messages').innerHTML, /feedback-btn[^>]*disabled/);
            if (outcome !== 'success') assert.match(h.warnings.at(-1), /피드백.*다시/);

            h.env.reply = async request => { serverRating = request.body.rating; return { ok: true }; };
            await h.run('submitFeedback(null, "msg", -1)');
            assert.equal(h.requests.length, 2, 'Success and failure must both release the pending guard');
            assert.equal(serverRating, -1);
            assert.equal(h.run('state.messages[0].feedback_rating'), serverRating);
            assert.match(h.get('messages').innerHTML, /dislike-btn active/);
        }
    },
    async deleteRecovery() {
        for (const remaining of [false, true]) {
            const h = setup();
            h.run(`state.messages = [{id: 'old-message', role: 'assistant', content: 'deleted text'}]; state.sessions = [{session_id: 'old-session'}, ${remaining ? "{session_id: 'remaining-session'}" : ''}]; renderMessages();`);
            h.active.set('nihongoActiveSessionId', 'old-session');
            h.local.set('nihongoMessages', 'deleted text');
            let release;
            h.env.reply = async r => {
                if (r.method === 'DELETE') return { ok: true };
                assert.equal(r.method, remaining ? 'GET' : 'POST');
                assert.equal(r.url, remaining ? '/api/sessions/remaining-session' : '/api/sessions');
                await new Promise(resolve => { release = resolve; });
                return { ok: false, status: 503 };
            };
            const pending = h.run('deleteSessionItem({stopPropagation() {}}, "old-session")');
            await new Promise(resolve => setImmediate(resolve));
            assert.equal(h.run('state.currentSessionId'), null, 'Deleted ID cleared before replacement finishes');
            assert.equal(h.run('state.messages.length'), 0);
            assert.equal(h.active.has('nihongoActiveSessionId'), false);
            assert.equal(h.local.has('nihongoMessages'), false);
            assert.doesNotMatch(h.get('messages').innerHTML, /deleted text/);
            release();
            await pending;
            assert.equal(h.run('state.isSessionTransition'), false);
            assert.ok(h.warnings.some(x => /새 대화/.test(x)), 'Visible recovery instructions');
            h.get('messageInput').value = 'hello';
            const before = h.requests.length;
            await h.run('sendMessage()');
            assert.equal(h.requests.length, before, 'No chat with deleted or null session');
            assert.equal(h.get('messageInput').value, 'hello');
        }
    },
    async switchSettings() {
        const h = setup();
        const session = { session_id: 'restored-session', partner_name: 'Hana', difficulty: 'advanced', topic: 'travel', roleplay_id: 'hotel', roleplay_args: { city: 'Kyoto' } };
        h.env.reply = async r => {
            assert.equal(r.method, 'GET');
            return { ok: true, json: async () => ({ session, messages: [{ id: 'saved-message', role: 'assistant', content: 'saved' }] }) };
        };
        await h.run('switchSession("restored-session", false)');
        assert.equal(h.run('state.settings.partnerName'), 'Hana');
        assert.equal(h.run('state.settings.difficulty'), 'advanced');
        assert.equal(h.run('state.settings.topic'), 'travel');
        assert.equal(h.run('state.settings.roleplayId'), 'hotel');
        assert.equal(h.run('state.settings.roleplayArgs.city'), 'Kyoto');
        assert.equal(h.get('partnerName').value, 'Hana');
        assert.match(h.get('difficultyStatus').textContent, /고급/);
        assert.equal(JSON.parse(h.local.get('nihongoSettings')).roleplayArgs.city, 'Kyoto');
        assert.equal(JSON.parse(h.local.get('nihongoMessages'))[0].id, 'saved-message');
        const before = h.run('JSON.stringify(state)');
        for (const data of [{}, { session: { ...session, session_id: 'wrong' }, messages: [] }, { session, messages: {} }]) {
            h.env.reply = async () => ({ ok: true, json: async () => data });
            await h.run('switchSession("restored-session", false)');
            assert.equal(h.run('JSON.stringify(state)'), before, 'Invalid response must preserve state');
        }
        h.env.reply = async r => ({ ok: true, json: async () => ({ session: { ...session, session_id: 'created-session' } }) });
        await h.run('startNewSession(false)');
        assert.deepEqual(h.requests.at(-1).body.roleplay_args, { city: 'Kyoto' });
    },
    async settingsQuota() {
        const h = setup();
        h.env.failCache = true;
        h.run('loadSettings()');
        assert.equal(h.get('partnerName').value, '유키');
        assert.ok(h.warnings.some(x => /브라우저.*저장/.test(x)));
    },
    async sessionQuota() {
        const h = setup();
        h.env.failCache = true;
        h.env.reply = async () => ({ ok: true, json: async () => ({ session: { session_id: 'created' } }) });
        assert.equal(await h.run('startNewSession(false)'), true, 'Cache failure cannot undo server activation');
        assert.equal(h.run('state.currentSessionId'), 'created');
        assert.equal(h.run('state.isSessionTransition'), false);
        assert.equal(h.run('state.messages[0].persisted'), false);
        assert.ok(h.warnings.some(x => /브라우저.*저장/.test(x)));
    },
    async quota() {
        const h = setup();
        h.env.failCache = true;
        h.get('messageInput').value = 'hello';
        await h.run('sendMessage()');
        assert.equal(h.requests.length, 1, 'Quota failure must not block chat');
        assert.equal(h.run('state.isLoading'), false);
        assert.equal(h.get('sendBtn').disabled, false);
        assert.equal(h.run('state.messages.at(-1).content'), 'reply');
        assert.ok(h.warnings.some(x => /브라우저.*저장/.test(x)));
    }
};
const watchdog = setTimeout(() => { console.error('Harness timed out'); process.exit(1); }, 5000);
(async () => {
    for (const [name, test] of Object.entries(tests)) {
        if (process.argv[2] && process.argv[2] !== name) continue;
        await test();
        console.log('PASS: ' + name);
    }
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
