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
const context = vm.createContext({
    console, setTimeout: () => {},
    document: {
        getElementById: getElement,
        addEventListener() {},
        querySelectorAll: () => [],
        querySelector: () => ({ dataset: { value: 'beginner' } })
    },
    localStorage: { setItem() {} }, sessionStorage: { setItem() {} },
    fetch: async (url, options) => {
        requests.push({ url, body: JSON.parse(options.body) });
        return { ok: true, json: async () => ({ session: { session_id: 'new-session' } }) };
    }
});
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
vm.runInContext(`
    escapeHTML = value => value;
    mcpPrompts = [{id: null, name: 'General'}, {id: 'cafe', name: 'Cafe'}, {id: 'hotel', name: 'Hotel'}];
    state.currentSessionId = 'old-session';
    state.messages = [{content: 'old conversation'}];
    addWelcomeMessage = () => { state.messages.push({content: 'welcome:' + state.settings.roleplayId}); };
    renderSessionList = () => {};
`, context);

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
})().catch(error => { console.error(error); process.exitCode = 1; });
