const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function element() {
    const classes = new Set();
    return {
        value: '유키', checked: true, style: {}, dataset: {}, innerHTML: '',
        classList: {
            add: name => classes.add(name),
            remove: name => classes.delete(name),
            contains: name => classes.has(name),
            toggle(name, force) {
                const enabled = force === undefined ? !classes.has(name) : force;
                if (enabled) classes.add(name); else classes.delete(name);
            }
        }
    };
}

const elements = new Map();
const getElement = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
};
const requests = [];
const saved = new Map();
const activeSession = new Map();
let argumentInputs = [];
let responseMode = 'success';
let releaseResponse;
const expectedErrors = [];
const warnings = [];
let failedStorageKey = null;
const context = vm.createContext({
    alert: message => warnings.push(message),
    console: { ...console, error: (...args) => expectedErrors.push(args) }, setTimeout: () => {},
    document: {
        getElementById: getElement,
        addEventListener() {},
        querySelectorAll: selector => selector === '.rp-arg-input' ? argumentInputs : [],
        querySelector: () => ({ dataset: { value: 'beginner' } })
    },
    localStorage: { setItem: (key, value) => {
        if (key === failedStorageKey) throw new DOMException('Storage full', 'QuotaExceededError');
        saved.set(key, value);
    } },
    sessionStorage: { setItem: (key, value) => activeSession.set(key, value) },
    fetch: async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        if (responseMode === 'http-error') return { ok: false, status: 503 };
        if (responseMode === 'network-error') throw new Error('Network unavailable');
        if (responseMode === 'json-error') return { ok: true, json: async () => { throw new Error('Invalid JSON'); } };
        if (responseMode === 'invalid-session') return { ok: true, json: async () => ({ session: {} }) };
        if (responseMode === 'pending') await new Promise(resolve => { releaseResponse = resolve; });
        return { ok: true, json: async () => ({ session: { session_id: 'new-session' } }) };
    }
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
vm.runInContext(`
    escapeHTML = value => value;
    mcpPrompts = [{id: null, name: 'General'}, {id: 'cafe', name: 'Cafe', welcome_message: 'welcome:cafe'}, {id: 'hotel', name: 'Hotel', welcome_message: 'welcome:hotel'}];
    state.currentSessionId = 'old-session';
    state.messages = [{content: 'old conversation'}];
    renderMessages = () => {};
    renderSessionList = () => {};
`, context);

const watchdog = setTimeout(() => { console.error('Harness did not complete'); process.exit(1); }, 5000);
(async () => {
    vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'cafe'); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 1, 'Saving a changed roleplay must create a session');
    assert.equal(requests[0].body.roleplay_id, 'cafe');
    assert.equal(vm.runInContext('state.currentSessionId', context), 'new-session');
    assert.equal(vm.runInContext('state.messages[0].content', context), 'welcome:cafe');
    assert.equal(vm.runInContext('state.messages.length', context), 1);
    assert.equal(getElement('settingsModal').classList.contains('show'), false);
    console.log('PASS: roleplay save creates a new conversation with the selected scenario');
    vm.runInContext(`toggleSettings(); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 1, 'Unchanged settings must not create a session');

    vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'hotel'); toggleSettings();`, context);
    assert.equal(vm.runInContext('state.settings.roleplayId', context), 'cafe', 'Cancel must not change active settings');
    vm.runInContext(`toggleSettings(); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 1, 'Reopening must discard the cancelled choice');

    vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'hotel'); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 2, 'Switching between scenarios must create a session');
    assert.equal(requests[1].body.roleplay_id, 'hotel');

    vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, null); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 3, 'Returning to general chat must create a session');
    assert.equal(requests[2].body.roleplay_id, null);
    console.log('PASS: unchanged save, cancelled selection, scenario switch, general chat');
    const beforeFailure = vm.runInContext('JSON.stringify({settings: state.settings, messages: state.messages, id: state.currentSessionId, sessions: state.sessions})', context);
    const persistedBeforeFailure = saved.get('nihongoSettings');
    responseMode = 'http-error';
    await vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'hotel'); saveSettings();`, context);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(vm.runInContext('JSON.stringify({settings: state.settings, messages: state.messages, id: state.currentSessionId, sessions: state.sessions})', context), beforeFailure, 'Failed session creation must preserve active settings and conversation');
    assert.equal(saved.get('nihongoSettings'), persistedBeforeFailure, 'Failed save must not persist the draft');
    assert.equal(getElement('settingsModal').classList.contains('show'), true, 'Failure must keep the settings open for retry');
    assert.match(getElement('settingsError').textContent, /다시/);
    responseMode = 'success';
    await vm.runInContext('saveSettings()', context);
    assert.equal(vm.runInContext('state.settings.roleplayId', context), 'hotel');
    assert.equal(getElement('settingsModal').classList.contains('show'), false);
    console.log('PASS: HTTP failure preserves settings and conversation; retry succeeds');
    responseMode = 'pending';
    const requestCount = requests.length;
    const pendingSave = vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'cafe'); saveSettings();`, context);
    const repeatedSave = vm.runInContext('saveSettings()', context);
    assert.equal(requests.length, requestCount + 1, 'Repeated save must not create duplicate sessions');
    assert.equal(vm.runInContext('state.settings.roleplayId', context), 'hotel', 'Pending save must keep active settings');
    assert.equal(getElement('saveSettingsBtn').disabled, true);
    vm.runInContext('toggleSettings()', context);
    assert.equal(getElement('settingsModal').classList.contains('show'), true, 'Keep pending form open');
    await vm.runInContext('sendMessage(); switchSession("other"); startNewSession(false);', context);
    assert.equal(requests.length, requestCount + 1, 'Pending save must block conflicting chat operations');
    releaseResponse();
    await pendingSave;
    await repeatedSave;
    assert.equal(vm.runInContext('state.settings.roleplayId', context), 'cafe');
    assert.equal(getElement('saveSettingsBtn').disabled, false);
    responseMode = 'success';
    console.log('PASS: pending saves are isolated and duplicate submission is blocked');
    for (const mode of ['network-error', 'json-error', 'invalid-session']) {
        const before = vm.runInContext('JSON.stringify(state)', context);
        const persisted = saved.get('nihongoSettings');
        const active = activeSession.get('nihongoActiveSessionId');
        responseMode = mode;
        await vm.runInContext(`toggleSettings(); selectRoleplay({classList: {add() {}}}, 'hotel'); saveSettings();`, context);
        assert.equal(vm.runInContext('JSON.stringify(state)', context), before, mode + ': state unchanged');
        assert.equal(saved.get('nihongoSettings'), persisted);
        assert.equal(activeSession.get('nihongoActiveSessionId'), active);
        assert.equal(getElement('settingsModal').classList.contains('show'), true);
        assert.equal(getElement('saveSettingsBtn').disabled, false);
        vm.runInContext('closeSettingsOnOverlay({target: settingsModal})', context);
        assert.equal(getElement('settingsModal').classList.contains('show'), false);
    }
    responseMode = 'success';
    console.log('PASS: network, JSON and invalid session failures preserve all state');

    vm.runInContext(`mcpPrompts.find(p => p.id === 'cafe').arguments = [{name: 'drink', default: 'tea'}]; toggleSettings();`, context);
    assert.match(getElement('roleplayArgsContainer').innerHTML, /value="tea"/);
    argumentInputs = [{dataset: {argName: 'drink'}, value: ' coffee '}];
    const beforeArgs = requests.length;
    await vm.runInContext('saveSettings()', context);
    assert.equal(requests.length, beforeArgs + 1, 'Arguments-only change starts a session');
    assert.equal(vm.runInContext('state.settings.roleplayArgs.drink', context), 'coffee');
    assert.equal(JSON.parse(saved.get('nihongoSettings')).roleplayArgs.drink, 'coffee');
    vm.runInContext('toggleSettings()', context);
    argumentInputs[0].value = 'juice';
    responseMode = 'http-error';
    await vm.runInContext('saveSettings()', context);
    assert.equal(vm.runInContext('state.settings.roleplayArgs.drink', context), 'coffee');
    vm.runInContext('closeSettingsOnOverlay({target: settingsModal}); toggleSettings();', context);
    assert.match(getElement('roleplayArgsContainer').innerHTML, /value="coffee"/);
    assert.equal(getElement('settingsError').textContent, '');
    responseMode = 'success';
    console.log('PASS: argument changes, failure preservation and overlay cancellation');

    const beforeBusy = requests.length;
    vm.runInContext('state.isLoading = true', context);
    await vm.runInContext('saveSettings()', context);
    assert.equal(requests.length, beforeBusy, 'Do not change settings during an AI reply');
    assert.match(getElement('settingsError').textContent, /다시/);
    vm.runInContext('state.isLoading = false', context);
    assert.ok(expectedErrors.length > 0, 'Failure paths were exercised');
    console.log('PASS: settings save waits for active chat replies');
    argumentInputs = [];
    for (const key of ['nihongoSettings', 'nihongoMessages']) {
        const scenario = key === 'nihongoSettings' ? 'hotel' : 'cafe';
        failedStorageKey = key;
        const warningCount = warnings.length;
        await vm.runInContext(`selectRoleplay({classList: {add() {}}}, '${scenario}'); saveSettings();`, context);
        assert.equal(vm.runInContext('state.settings.roleplayId', context), scenario);
        assert.equal(vm.runInContext('state.messages[0].content', context), 'welcome:' + scenario);
        assert.equal(getElement('settingsError').textContent, '', 'An activated session must not be reported as a failed save');
        assert.equal(warnings.length, warningCount + 1, 'Cache failure must display a specific warning');
        assert.match(warnings.at(-1), /브라우저.*저장/);
        assert.equal(vm.runInContext('state.isSavingSettings || state.isSessionTransition', context), false);
        failedStorageKey = null;
    }
    console.log('PASS: real welcome/message and settings cache failures retain activation with truthful warnings');
})().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => clearTimeout(watchdog));
