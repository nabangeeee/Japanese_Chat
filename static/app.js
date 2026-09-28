// 상태 관리
let state = {
    messages: [],
    sessions: [],
    currentSessionId: null,
    memories: [],
    isLoading: false,
    isSavingSettings: false,
    isSessionTransition: false,
    settings: {
        apiKey: '',
        partnerName: '유키',
        difficulty: 'beginner',
        topic: 'free',
        roleplayId: null,
        roleplayArgs: {},
        showTranslation: true,
        showFurigana: true
    }
};

let mcpPrompts = [];
let draftRoleplayId = null;

// 난이도/주제 한글 이름 매핑
const DIFFICULTY_NAMES = {
    'beginner': '초급',
    'intermediate': '중급',
    'advanced': '고급'
};

// DOM 요소
const messagesContainer = document.getElementById('messages');
const messageInput = document.getElementById('messageInput');
const sendBtn = document.getElementById('sendBtn');
const settingsModal = document.getElementById('settingsModal');

// 초기화
document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    initSessionSystem();
    fetchMcpPrompts();
    
    // 자동 높이 조절
    messageInput.addEventListener('input', autoResize);
});

function autoResize() {
    messageInput.style.height = 'auto';
    messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + 'px';
}

// MCP Prompts 서버에서 목록 가져오기
async function fetchMcpPrompts() {
    try {
        const res = await fetch('/api/mcp/prompts');
        if (res.ok) {
            const data = await res.json();
            mcpPrompts = data.prompts || [];
            renderMcpPromptsUI();
            updateStatusBar();
            if (state.settings.roleplayId && state.messages.length === 1 && state.messages[0].persisted === false) {
                addWelcomeMessage();
            }
        }
    } catch (e) {
        console.error('MCP Prompts 로드 실패:', e);
    }
}

// MCP Prompts UI 동적 렌더링
function renderMcpPromptsUI() {
    const container = document.getElementById('roleplayContainer');
    if (!container) return;

    let html = '';
    mcpPrompts.forEach(prompt => {
        const isActive = prompt.id === draftRoleplayId || (!draftRoleplayId && prompt.id === null);
        html += `
            <button type="button" class="roleplay-card ${isActive ? 'active' : ''}" onclick="selectRoleplay(this, ${prompt.id ? `'${prompt.id}'` : 'null'})">
                <div class="rp-card-header">
                    <span class="rp-card-title">${escapeHTML(scenarioName(prompt))}</span>
                    <span class="rp-card-badge">${escapeHTML(prompt.category)}</span>
                </div>
                <p class="rp-card-desc">${escapeHTML(prompt.description)}</p>
            </button>
        `;
    });

    container.innerHTML = html;
    renderRoleplayArgsForm();
}

function selectRoleplay(element, promptId) {
    document.querySelectorAll('.roleplay-card').forEach(card => card.classList.remove('active'));
    element.classList.add('active');
    
    draftRoleplayId = promptId;
    renderRoleplayArgsForm();
}

function renderRoleplayArgsForm() {
    const argsContainer = document.getElementById('roleplayArgsContainer');
    if (!argsContainer) return;

    const currentPrompt = mcpPrompts.find(p => p.id === draftRoleplayId);
    if (!currentPrompt || !currentPrompt.arguments || currentPrompt.arguments.length === 0) {
        argsContainer.style.display = 'none';
        argsContainer.innerHTML = '';
        return;
    }

    argsContainer.style.display = 'block';
    let html = `<div class="rp-args-title">${escapeHTML(scenarioName(currentPrompt))} · 세부 설정</div>`;

    currentPrompt.arguments.forEach(arg => {
        const val = state.settings.roleplayArgs[arg.name] || arg.default || '';
        html += `
            <div class="rp-arg-row">
                <label class="rp-arg-label">${escapeHTML(arg.description || arg.name)}</label>
                <input type="text" class="rp-arg-input" data-arg-name="${arg.name}" value="${escapeAttribute(val)}" placeholder="${escapeAttribute(arg.default || '')}">
            </div>
        `;
    });

    argsContainer.innerHTML = html;
}

// 설정 로드
function loadSettings() {
    try {
        const saved = JSON.parse(localStorage.getItem('nihongoSettings') || 'null');
        if (saved && typeof saved === 'object' && !Array.isArray(saved)) {
            for (const key of ['partnerName', 'topic']) {
                if (typeof saved[key] === 'string') state.settings[key] = saved[key];
            }
            if (Object.prototype.hasOwnProperty.call(DIFFICULTY_NAMES, saved.difficulty)) {
                state.settings.difficulty = saved.difficulty;
            }
            if (saved.roleplayId === null || typeof saved.roleplayId === 'string') {
                state.settings.roleplayId = saved.roleplayId;
            }
            if (saved.roleplayArgs && typeof saved.roleplayArgs === 'object' && !Array.isArray(saved.roleplayArgs)) {
                state.settings.roleplayArgs = Object.fromEntries(
                    Object.entries(saved.roleplayArgs).filter(([, value]) => typeof value === 'string')
                );
            }
            for (const key of ['showTranslation', 'showFurigana']) {
                if (typeof saved[key] === 'boolean') state.settings[key] = saved[key];
            }
        }
    } catch (err) {
        console.error('Settings cache read failed; using defaults:', err);
    }
    // Credentials are server-managed; discard keys saved by older providers.
    state.settings.apiKey = '';
    try {
        localStorage.setItem('nihongoSettings', JSON.stringify(state.settings));
    } catch (err) {
        console.error('Settings cache write failed:', err);
        alert('이 브라우저에 설정을 저장하지 못했습니다. 대화는 계속할 수 있습니다.');
    }
    applySettingsToUI();
}

// 설정 UI에 적용
function applySettingsToUI() {
    draftRoleplayId = state.settings.roleplayId;
    document.getElementById('partnerName').value = state.settings.partnerName;
    document.getElementById('showTranslation').checked = state.settings.showTranslation;
    document.getElementById('showFurigana').checked = state.settings.showFurigana;
    
    // 난이도 버튼
    document.querySelectorAll('.segment').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.value === state.settings.difficulty);
    });
    
    // MCP Prompts 재렌더링
    renderMcpPromptsUI();

    // 상태 바 업데이트
    updateStatusBar();
    
    // 설정 모달 명시적 닫기
    const modal = document.getElementById('settingsModal');
    if (modal) {
        modal.classList.remove('show');
    }
}

// 상태 바 업데이트
function updateStatusBar() {
    const difficultyStatus = document.getElementById('difficultyStatus');
    const roleplayStatus = document.getElementById('roleplayStatus');
    const partner = document.getElementById('partnerStatus');
    if (partner) partner.textContent = state.settings.partnerName + '와 함께';
    
    if (difficultyStatus) {
        difficultyStatus.textContent = DIFFICULTY_NAMES[state.settings.difficulty];
    }
    if (roleplayStatus) {
        if (state.settings.roleplayId) {
            const promptObj = mcpPrompts.find(p => p.id === state.settings.roleplayId);
            roleplayStatus.textContent = promptObj ? scenarioName(promptObj) : '상황 연습';
        } else {
            roleplayStatus.textContent = '자유 대화';
        }
    }
}

// 설정 저장
async function saveSettings() {
    if (state.isSavingSettings) return;
    const errorEl = document.getElementById('settingsError');
    if (state.isLoading || state.isSessionTransition) {
        errorEl.textContent = '대화 처리가 끝난 뒤 다시 저장해 주세요.';
        return;
    }
    state.isSavingSettings = true;
    const saveButton = document.getElementById('saveSettingsBtn');
    saveButton.disabled = true;
    saveButton.textContent = '저장 중…';
    errorEl.textContent = '';
    try {
        const partnerNameEl = document.getElementById('partnerName');
        const showTransEl = document.getElementById('showTranslation');
        const showFuriEl = document.getElementById('showFurigana');

        const prevDifficulty = state.settings ? state.settings.difficulty : 'beginner';
        const prevRoleplayId = state.settings ? state.settings.roleplayId : null;
        const prevRoleplayArgs = state.settings ? state.settings.roleplayArgs : {};
        
        const activeSegment = document.querySelector('#settingsModal .segment.active');
        const newDifficulty = activeSegment ? activeSegment.dataset.value : 'beginner';

        const roleplayArgs = {};
        document.querySelectorAll('.rp-arg-input').forEach(input => {
            const argName = input.dataset.argName;
            if (argName) {
                roleplayArgs[argName] = input.value.trim();
            }
        });

        const nextSettings = {
            apiKey: '',
            partnerName: partnerNameEl ? partnerNameEl.value : '유키',
            difficulty: newDifficulty,
            topic: 'free',
            roleplayId: draftRoleplayId,
            roleplayArgs: roleplayArgs,
            showTranslation: showTransEl ? showTransEl.checked : true,
            showFurigana: showFuriEl ? showFuriEl.checked : true
        };
        
        const settingsChanged = (
            prevDifficulty !== newDifficulty ||
            prevRoleplayId !== nextSettings.roleplayId ||
            JSON.stringify(prevRoleplayArgs) !== JSON.stringify(roleplayArgs)
        );
        
        if (settingsChanged) {
            if (!await startNewSession(false, nextSettings)) {
                throw new Error('Session creation failed');
            }
        } else {
            state.settings = nextSettings;
            if (state.messages.length === 0) addWelcomeMessage();
        }
        try {
            localStorage.setItem('nihongoSettings', JSON.stringify(state.settings));
        } catch (err) {
            console.error('Settings cache write failed:', err);
            alert('설정은 적용되었지만 이 브라우저에 저장하지 못했습니다. 새로고침하면 설정이 유지되지 않을 수 있습니다.');
        }
        updateStatusBar();
        settingsModal.classList.remove('show');
        document.getElementById('settingsError').textContent = '';
    } catch (err) {
        console.error('Error saving settings:', err);
        document.getElementById('settingsError').textContent = '설정을 저장하지 못했습니다. 연결을 확인하고 다시 저장해 주세요.';
    } finally {
        state.isSavingSettings = false;
        saveButton.disabled = false;
        saveButton.textContent = '설정 저장하기';
    }
}

async function initSessionSystem() {
    try {
        const res = await fetch('/api/sessions');
        if (res.ok) {
            const data = await res.json();
            state.sessions = data.sessions || [];
        }
    } catch (e) {
        console.error('Session list load failed:', e);
    }

    // 새로고침할 때 이전 활성 대화와 로컬 메시지 캐시를 이어받지 않는다.
    sessionStorage.removeItem('nihongoActiveSessionId');
    localStorage.removeItem('nihongoMessages');
    state.currentSessionId = null;
    state.messages = [];
    await startNewSession(false);

    // 세션 생성 API가 실패해도 이전 대화 대신 새 로컬 대화 화면을 표시한다.
    if (state.messages.length === 0) {
        addWelcomeMessage();
    }
}

async function startNewSession(closeDrawer = true, settings = state.settings) {
    if (state.isLoading || state.isSessionTransition) return false;
    state.isSessionTransition = true;
    try {
        let title = `자유 대화 (${DIFFICULTY_NAMES[settings.difficulty] || '초급'})`;
        if (settings.roleplayId) {
            const rp = mcpPrompts.find(p => p.id === settings.roleplayId);
            if (rp) {
                title = `${scenarioName(rp)} (${DIFFICULTY_NAMES[settings.difficulty] || '초급'})`;
            }
        }
        
        const res = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                partner_name: settings.partnerName,
                difficulty: settings.difficulty,
                topic: settings.topic,
                roleplay_id: settings.roleplayId,
                roleplay_args: settings.roleplayArgs || {}
            })
        });
        if (res.ok) {
            const data = await res.json();
            const newSess = data.session;
            if (!newSess || typeof newSess.session_id !== 'string' || !newSess.session_id) {
                return false;
            }
            try {
                sessionStorage.setItem('nihongoActiveSessionId', newSess.session_id);
            } catch (err) {
                console.error('Session cache write failed:', err);
                alert('대화는 생성되었지만 이 브라우저에 저장하지 못했습니다.');
            }
            state.settings = settings;
            state.sessions.unshift(newSess);
            state.currentSessionId = newSess.session_id;
            state.messages = [];
            
            addWelcomeMessage();
            renderSessionList();
            if (closeDrawer) toggleSessionDrawer();
            return true;
        }
    } catch (e) {
        console.error('Create session failed:', e);
    } finally {
        state.isSessionTransition = false;
    }
    return false;
}

async function switchSession(sessionId, closeDrawer = true) {
    if (state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    state.isSessionTransition = true;
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        if (res.ok) {
            const data = await res.json();
            const session = data.session;
            if (!session || session.session_id !== sessionId || !Array.isArray(data.messages) ||
                typeof session.partner_name !== 'string' || !DIFFICULTY_NAMES[session.difficulty] ||
                typeof session.topic !== 'string' ||
                !(session.roleplay_id === null || typeof session.roleplay_id === 'string') ||
                !session.roleplay_args || typeof session.roleplay_args !== 'object' || Array.isArray(session.roleplay_args)) {
                throw new Error('Invalid session response');
            }
            state.currentSessionId = sessionId;
            state.settings = {
                ...state.settings,
                partnerName: session.partner_name,
                difficulty: session.difficulty,
                topic: session.topic,
                roleplayId: session.roleplay_id,
                roleplayArgs: session.roleplay_args
            };
            state.messages = data.messages;
            try {
                sessionStorage.setItem('nihongoActiveSessionId', sessionId);
                localStorage.setItem('nihongoSettings', JSON.stringify(state.settings));
            } catch (err) {
                console.error('Session cache write failed:', err);
                alert('대화는 열었지만 이 브라우저에 설정을 저장하지 못했습니다.');
            }
            applySettingsToUI();
            saveMessages();
            
            // 세션에 저장된 메시지가 없으면 웰컴 메시지 추가
            if (state.messages.length === 0) {
                addWelcomeMessage();
            } else {
                renderMessages();
            }
            
            renderSessionList();
            if (closeDrawer) toggleSessionDrawer();
        }
    } catch (e) {
        console.error('Switch session failed:', e);
    } finally {
        state.isSessionTransition = false;
    }
}

async function deleteSessionItem(event, sessionId) {
    event.stopPropagation();
    if (state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    if (!confirm('이 대화 세션을 삭제하시겠습니까?')) return;
    state.isSessionTransition = true;
    try {
        const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        state.isSessionTransition = false;
        if (res.ok) {
            state.sessions = state.sessions.filter(s => s.session_id !== sessionId);
            if (state.currentSessionId === sessionId) {
                state.currentSessionId = null;
                state.messages = [];
                for (const [storage, key] of [[sessionStorage, 'nihongoActiveSessionId'], [localStorage, 'nihongoMessages']]) {
                    try {
                        storage.removeItem(key);
                    } catch (err) {
                        console.error('Deleted session cache removal failed:', err);
                    }
                }
                renderMessages();
                renderSessionList();
                if (state.sessions.length > 0) {
                    await switchSession(state.sessions[0].session_id, false);
                } else {
                    await startNewSession(false);
                }
                if (!state.currentSessionId) {
                    messagesContainer.innerHTML = '<p>대화를 열지 못했습니다. 새 대화를 시작하거나 다른 세션을 선택해 주세요.</p>';
                    alert('대화를 열지 못했습니다. 새 대화를 시작하거나 다른 세션을 선택해 주세요.');
                }
            } else {
                renderSessionList();
            }
        }
    } catch (e) {
        console.error('Delete session failed:', e);
    } finally {
        state.isSessionTransition = false;
    }
}

function toggleSessionDrawer() {
    const backdrop = document.getElementById('drawerBackdrop');
    const drawer = document.getElementById('sessionDrawer');
    if (!backdrop || !drawer) return;

    const opening = !drawer.classList.contains('active');
    if (opening) renderSessionList();
    drawer.classList.toggle('active', opening);
    backdrop.classList.toggle('active', opening);
    syncOverlayFocus();
}

function renderSessionList() {
    const container = document.getElementById('sessionList');
    if (!container) return;

    if (state.sessions.length === 0) {
        container.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px;">저장된 세션이 없습니다.</p>';
        return;
    }

    container.innerHTML = state.sessions.map(s => {
        const isActive = s.session_id === state.currentSessionId;
        const dateStr = new Date(s.updated_at || s.created_at).toLocaleDateString('ko-KR', {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
        return `
            <div class="session-item ${isActive ? 'active' : ''}" onclick="switchSession('${s.session_id}')">
                <div class="session-item-info">
                    <span class="session-item-title">${escapeHTML(s.title || '대화')}</span>
                    <span class="session-item-sub">${escapeHTML(s.partner_name)} • ${dateStr}</span>
                </div>
                <button class="session-delete-btn" onclick="deleteSessionItem(event, '${s.session_id}')" aria-label="대화 삭제" title="삭제">${uiIcon('trash')}</button>
            </div>
        `;
    }).join('');
}

async function toggleMemoryModal() {
    const modalBackdrop = document.getElementById('memoryModalBackdrop');
    if (!modalBackdrop) return;

    const isActive = modalBackdrop.classList.contains('show');
    if (isActive) {
        modalBackdrop.classList.remove('show');
        syncOverlayFocus();
    } else {
        modalBackdrop.classList.add('show');
        syncOverlayFocus();
        await loadAndRenderMemories();
    }
}

let currentMemoryTab = 'errors';

function switchMemoryTab(tabName) {
    currentMemoryTab = tabName;
    const btnErrors = document.getElementById('tabErrorsBtn');
    const btnFacts = document.getElementById('tabFactsBtn');
    document.getElementById('tabPracticeBtn').classList.toggle('active', tabName === 'practice');
    
    if (tabName === 'errors') {
        if (btnErrors) btnErrors.classList.add('active');
        if (btnFacts) btnFacts.classList.remove('active');
    } else {
        if (btnFacts) btnFacts.classList.toggle('active', tabName === 'facts');
        if (btnErrors) btnErrors.classList.remove('active');
    }
    loadAndRenderMemories();
}

async function loadAndRenderMemories() {
    const body = document.getElementById('memoryListBody');
    if (!body) return;
    body.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px;">로딩 중...</p>';
    
    if (currentMemoryTab === 'practice') {
        await loadPractice();
        return;
    }
    if (currentMemoryTab === 'errors') {
        try {
            const res = await fetch('/api/memories');
            if (!res.ok) throw new Error('Memory request failed');
            if (currentMemoryTab !== 'errors') return;
            if (res.ok) {
                const data = await res.json();
                state.memories = data.memories || [];
                if (state.memories.length === 0) {
                    body.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px; line-height: 1.6;">아직 저장된 오답이 없어요.<br>AI와 일본어로 회화하면서 틀린 문법이 있을 때 자동으로 오답 노트에 저장돼요.</p>';
                    return;
                }
                body.innerHTML = state.memories.map(m => `
                    <div class="memory-card">
                        <div class="memory-card-header">
                            <span class="memory-badge">틀렸던 표현</span>
                            <span>${new Date(m.created_at).toLocaleDateString('ko-KR')}</span>
                        </div>
                        <div class="memory-original">${escapeHTML(m.original_text || '')}</div>
                        <div class="memory-corrected">${escapeHTML(m.corrected_text || '')}</div>
                        ${m.explanation ? `<div class="memory-explanation">${escapeHTML(m.explanation)}</div>` : ''}
                    </div>
                `).join('');
            }
        } catch (e) {
            console.error('Load memories failed:', e);
            body.innerHTML = '<p style="text-align:center; color: red;">오답 노트를 불러오는데 실패했습니다.</p>';
        }
    } else {
        // 장기 기억 프로필 탭
        try {
            const res = await fetch('/api/facts');
            if (!res.ok) throw new Error('Facts request failed');
            if (currentMemoryTab !== 'facts') return;
            if (res.ok) {
                const data = await res.json();
                const facts = data.facts || [];
                const summaries = data.summaries || [];
                
                if (facts.length === 0 && summaries.length === 0) {
                    body.innerHTML = `
                        <div class="memory-card">
                            <div class="memory-card-header">
                                <span class="memory-badge">나의 학습 기록</span>
                            </div>
                            <div class="memory-corrected">아직 함께 나눈 이야기가 없어요</div>
                            <div class="memory-explanation">
                                대화를 나누면 이야기한 내용과 관심사를 여기에 정리해 드려요.
                            </div>
                        </div>
                    `;
                    return;
                }
                
                let html = '';
                
                if (facts.length > 0) {
                    html += facts.map(f => `
                        <div class="memory-card">
                            <div class="memory-card-header">
                                <span class="memory-badge">나에 대해 기억한 내용</span>
                                <span>${new Date(f.updated_at).toLocaleDateString('ko-KR')}</span>
                            </div>
                            <div class="memory-corrected">${escapeHTML(f.fact_key || '')}</div>
                            <div class="memory-explanation">${escapeHTML(f.fact_value || '')}</div>
                        </div>
                    `).join('');
                }
                
                if (summaries.length > 0) {
                    html += summaries.map(s => `
                        <div class="memory-card">
                            <div class="memory-card-header">
                                <span class="memory-badge">대화 요약</span>
                                <span>${new Date(s.updated_at).toLocaleDateString('ko-KR')}</span>
                            </div>
                            <div class="memory-corrected">${escapeHTML(s.title || '대화 세션 요약')}</div>
                            <div class="memory-explanation">${escapeHTML(s.summary || '')}</div>
                        </div>
                    `).join('');
                }
                
                body.innerHTML = html;
            }
        } catch (e) {
            console.error('Load facts failed:', e);
            body.innerHTML = '<p style="text-align:center; color: red;">장기 기억 프로필을 불러오는데 실패했습니다.</p>';
        }
    }
}

// 메시지 저장
function saveMessages() {
    try {
        localStorage.setItem('nihongoMessages', JSON.stringify(state.messages));
    } catch (err) {
        console.error('Message cache write failed:', err);
        alert('이 브라우저에 메시지를 저장하지 못했습니다. 대화는 계속할 수 있습니다.');
    }
}

// 환영 메시지 추가
function addWelcomeMessage() {
    let content = '';
    
    // 롤플레잉 모드일 경우 해당 MCP 시나리오의 맞춤형 웰컴 문구 사용
    if (state.settings.roleplayId && mcpPrompts.length > 0) {
        const rp = mcpPrompts.find(p => p.id === state.settings.roleplayId);
        if (rp && rp.welcome_message) {
            content = rp.welcome_message;
            // 템플릿 인자 치환 (예: {place}, {hotel_name} 등)
            if (rp.arguments && rp.arguments.length > 0) {
                rp.arguments.forEach(arg => {
                    const val = state.settings.roleplayArgs[arg.name] || arg.default || '';
                    content = content.replaceAll(`{${arg.name}}`, val);
                });
            }
        }
    }
    
    // 일반 대화 모드이거나 맞춤 문구가 없을 때 기본 웰컴 인사말 사용
    if (!content) {
        const welcomeMessages = [
            'こんにちは。今日は、どんな一日でしたか？',
            'こんにちは！好きなことについて、少しお話ししませんか？',
            'こんにちは。最近、楽しかったことを教えてください。'
        ];
        content = welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)];
    }
    
    const message = {
        id: Date.now().toString(),
        persisted: false,
        role: 'assistant',
        content: content,
        timestamp: new Date().toISOString()
    };
    
    state.messages = [message];
    try {
        saveMessages();
    } catch (err) {
        console.error('Welcome message cache write failed:', err);
        alert('새 대화는 시작되었지만 이 브라우저에 메시지를 저장하지 못했습니다. 로컬 대화 캐시가 유지되지 않을 수 있습니다.');
    }
    renderMessages();
}

// 메시지 렌더링
function renderMessages() {
    messagesContainer.innerHTML = state.messages.map(msg => createMessageHTML(msg)).join('');
    const hasConversation = state.messages.some(m => m.role === 'user' || (m.role === 'assistant' && m.persisted !== false));
    const panel = document.getElementById('conversationPanel');
    if (panel) panel.classList.toggle('has-conversation', hasConversation);
    const starters = document.getElementById('starterPrompts');
    if (starters) starters.hidden = hasConversation || Boolean(state.settings.roleplayId);
    updateStatusBar();
    scrollToBottom();
}

// 메시지 HTML 생성
function createMessageHTML(message) {
    const isUser = message.role === 'user';
    const time = new Date(message.timestamp).toLocaleTimeString('ko-KR', { 
        hour: '2-digit', 
        minute: '2-digit',
        hour12: false 
    });
    
    if (isUser) {
        return `
            <div class="message user">
                <div class="bubble-container">
                    <div class="bubble">${escapeHTML(message.content)}</div>
                    ${message.delivery === 'failed' ? `<div class="delivery-error" role="status">${escapeHTML(message.deliveryError || '전송하지 못했어요.')}
                        <button type="button" class="text-action" onclick="sendMessage('${message.id}')">다시 보내기</button>
                    </div>` : message.delivery === 'pending' ? '<span class="timestamp">보내는 중…</span>' : ''}
                    <span class="timestamp">${time}</span>
                </div>
            </div>
        `;
    } else {
        const canShowDetails = state.settings.showTranslation || state.settings.showFurigana;
        
        return `
            <div class="message assistant">
                <div class="avatar" aria-hidden="true">に</div>
                <div class="bubble-container">
                    <div class="bubble" onclick="toggleDetails('${message.id}')">
                        <span class="message-text">${renderAssistantText(message.content)}</span>
                        <div class="bubble-details ${message.detailsOpen ? 'show' : ''}" id="details-${message.id}">
                            ${messageDetailsHTML(message)}
                        </div>
                    </div>
                    <div class="message-footer-bar">
                        ${canShowDetails ? `<button class="tap-hint" onclick="toggleDetails('${message.id}')">번역 · 읽는 법 ${message.detailsOpen ? '접기' : '보기'}</button>` : ''}
                        ${message.id && message.persisted !== false ? `<div class="feedback-bar" id="feedback-bar-${message.id}">
                            <button class="feedback-btn like-btn ${message.feedback_rating === 1 ? 'active' : ''}" ${pendingFeedback.has(message.id) ? 'disabled' : ''} onclick="submitFeedback(event, '${message.id}', 1)" aria-label="도움이 되었어요" title="도움이 되었어요">${uiIcon('like')}</button>
                            <button class="feedback-btn dislike-btn ${message.feedback_rating === -1 ? 'active' : ''}" ${pendingFeedback.has(message.id) ? 'disabled' : ''} onclick="submitFeedback(event, '${message.id}', -1)" aria-label="어색한 답장이에요" title="어색하거나 피하고 싶은 답장이에요">${uiIcon('dislike')}</button>
                        </div>` : ''}
                    </div>
                    <span class="timestamp">${time}</span>
                </div>
            </div>
        `;
    }
}

const pendingFeedback = new Set();

async function submitFeedback(event, messageId, rating) {
    if (event) event.stopPropagation();
    const message = state.messages.find(m => m.id === messageId);
    if (!state.currentSessionId || !messageId || !message || message.role !== 'assistant' || message.persisted === false) return;
    if (pendingFeedback.has(messageId)) return;
    pendingFeedback.add(messageId);
    try {
        renderMessages();
        let feedbackText = null;

        // 서버에 피드백 저장
        const res = await fetch('/api/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message_id: messageId,
                session_id: state.currentSessionId,
                rating: rating,
                feedback_text: feedbackText,
                api_key: state.settings ? state.settings.apiKey : ''
            })
        });
        
        if (!res.ok) throw new Error('Feedback rejected');
        message.feedback_rating = rating;
        saveMessages();
    } catch (e) {
        console.error('Submit feedback failed:', e);
        alert('피드백을 저장하지 못했습니다. 다시 시도해 주세요.');
    } finally {
        pendingFeedback.delete(messageId);
        renderMessages();
    }
}

// HTML 이스케이프
function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function escapeAttribute(value) {
    return escapeHTML(String(value)).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function renderAssistantText(text) {
    // Only canonical HTTP(S) source links become HTML; all prose stays escaped.
    const pattern = /\[出典 (\d+)\]\((https?:\/\/[^\s)]+)\)/g;
    let html = '';
    let end = 0;
    for (const match of text.matchAll(pattern)) {
        html += escapeHTML(text.slice(end, match.index));
        const href = escapeHTML(match[2]).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
        html += `<a href="${href}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">出典 ${match[1]}</a>`;
        end = match.index + match[0].length;
    }
    return html + escapeHTML(text.slice(end));
}

function isValidFurigana(reading, source) {
    if (!reading || /[A-Za-z]/.test(reading)) return false;
    const hasKanji = /[\u3400-\u9FFF々〆ヶ]/.test(source || '');
    if (!hasKanji) return true;
    return /\([\u3040-\u309Fー]+\)/.test(reading);
}

const pendingDetails = new Set();

function messageDetailsHTML(message) {
    return [['furigana', '읽는 법', state.settings.showFurigana],
            ['translation', '한국어 번역', state.settings.showTranslation]]
        .filter(([, , enabled]) => enabled)
        .map(([field, label]) => {
            const error = message.detailErrors && message.detailErrors[field];
            const text = message[field];
            return `<div class="detail-section"><div class="detail-label">${label}</div>
                <div class="detail-text">${text ? escapeHTML(text) : error ? '불러오지 못했어요.' : '불러오는 중…'}</div>
                ${error ? `<button type="button" class="text-action" onclick="event.stopPropagation(); retryDetails('${message.id}')">다시 시도</button>` : ''}
            </div>`;
        }).join('');
}

function updateDetails(message) {
    if (!state.messages.includes(message)) return;
    const details = document.getElementById(`details-${message.id}`);
    if (details) details.innerHTML = messageDetailsHTML(message);
    saveMessages();
}

async function fetchDetails(message) {
    if (pendingDetails.has(message.id)) return;
    pendingDetails.add(message.id);
    message.detailErrors = {};
    if (!isValidFurigana(message.furigana, message.content)) delete message.furigana;
    updateDetails(message);
    try {
        await Promise.all([
            ['translation', '/api/translate', state.settings.showTranslation],
            ['furigana', '/api/furigana', state.settings.showFurigana]
        ].filter(([field, , enabled]) => enabled && !message[field]).map(async ([field, url]) => {
            try {
                const response = await fetch(url, {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({text: message.content, api_key: state.settings.apiKey || '',
                        message_id: message.persisted === false ? null : message.id})
                });
                if (!response.ok) throw new Error('Detail request failed');
                const data = await response.json();
                if (typeof data[field] !== 'string' || !data[field].trim() ||
                    (field === 'furigana' && !isValidFurigana(data[field], message.content))) {
                    throw new Error('Invalid detail');
                }
                message[field] = data[field];
            } catch (error) {
                message.detailErrors[field] = true;
            }
            updateDetails(message);
        }));
    } finally {
        pendingDetails.delete(message.id);
    }
}

async function retryDetails(messageId) {
    const message = state.messages.find(m => m.id === messageId);
    if (message) await fetchDetails(message);
}

async function toggleDetails(messageId) {
    const message = state.messages.find(m => m.id === messageId);
    const details = document.getElementById(`details-${messageId}`);
    if (!message || !details || !(state.settings.showTranslation || state.settings.showFurigana)) return;
    message.detailsOpen = !message.detailsOpen;
    details.classList.toggle('show', message.detailsOpen);
    if (message.detailsOpen) await fetchDetails(message);
    const button = document.querySelector(`#details-${messageId}`)?.closest('.bubble-container')?.querySelector('.tap-hint');
    if (button) button.textContent = '번역 · 읽는 법 ' + (message.detailsOpen ? '접기' : '보기');
}

// 타이핑 인디케이터
function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'typing-indicator';
    indicator.innerHTML = `
        <div class="avatar" aria-hidden="true">に</div>
        <div class="typing-dots">
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
            <div class="typing-dot"></div>
        </div>
    `;
    messagesContainer.appendChild(indicator);
    scrollToBottom();
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typingIndicator');
    if (indicator) {
        indicator.remove();
    }
}

// 스크롤
function scrollToBottom() {
    const chat = document.getElementById('chatContainer');
    if (chat) chat.scrollTop = chat.scrollHeight;
}

function newRequestId() {
    // getRandomValues also works when accessed over a local-network HTTP address.
    return '10000000-1000-4000-8000-100000000000'.replace(/[018]/g, c =>
        (Number(c) ^ crypto.getRandomValues(new Uint8Array(1))[0] & 15 >> Number(c) / 4).toString(16));
}

// 메시지 전송
async function sendMessage(retryId = null) {
    const failed = retryId ? state.messages.find(m => m.id === retryId && m.delivery === 'failed') : null;
    if (retryId && !failed) return;
    const content = failed ? failed.content : messageInput.value.trim();
    if (!content || state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    if (!state.currentSessionId) {
        alert('새 대화를 시작하거나 저장된 세션을 선택해 주세요.');
        return;
    }
    
    // 즉시 중복 전송 차단
    state.isLoading = true;
    sendBtn.disabled = true;
    

    const userMessage = failed || {
        id: newRequestId(), role: 'user', content,
        timestamp: new Date().toISOString()
    };
    userMessage.requestId = userMessage.requestId || userMessage.id;
    userMessage.delivery = 'pending';
    if (failed) state.messages = state.messages.filter(m => m !== failed);
    state.messages.push(userMessage);
    try {
        saveMessages();
        renderMessages();
        if (!failed) {
            messageInput.value = '';
            messageInput.style.height = 'auto';
        }

        showTypingIndicator();
    
        // 대화 히스토리 구성
        const history = state.messages.filter(m => !['failed', 'pending'].includes(m.delivery)).slice(-10).map(msg => ({
            role: msg.role,
            content: msg.content
        }));
        
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: content,
                history: history,
                request_id: userMessage.requestId,
                api_key: state.settings.apiKey,
                partner_name: state.settings.partnerName,
                difficulty: state.settings.difficulty,
                topic: state.settings.topic,
                roleplay_id: state.settings.roleplayId || null,
                roleplay_args: state.settings.roleplayArgs || {},
                session_id: state.currentSessionId
            })
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || '오류가 발생했습니다.');
        }
        
        const data = await response.json();
        userMessage.id = data.user_message_id;
        userMessage.delivery = 'sent';
        
        // 서버가 저장한 답장을 화면에 추가
        const assistantMessage = {
            id: data.message_id,
            role: 'assistant',
            content: data.response,
            timestamp: new Date().toISOString()
        };
        
        state.messages.push(assistantMessage);
        saveMessages();
        
    } catch (error) {
        userMessage.delivery = 'failed';
        userMessage.deliveryError = error.message || '전송하지 못했어요.';
        saveMessages();
    } finally {
        state.isLoading = false;
        sendBtn.disabled = false;
        hideTypingIndicator();
        renderMessages();
    }
}

// 엔터 키 처리 (한글/일본어 IME 글자 조합 중복 입력 방지)
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        if (event.isComposing) return;
        event.preventDefault();
        sendMessage();
    }
}

// 설정 모달
function toggleSettings() {
    if (state.isSavingSettings) return;
    if (!settingsModal.classList.contains('show')) {
        applySettingsToUI();
        document.getElementById('settingsError').textContent = '';
    }
    settingsModal.classList.toggle('show');
    syncOverlayFocus();
}

function closeSettingsOnOverlay(event) {
    if (event.target === settingsModal) {
        toggleSettings();
    }
}


function selectDifficulty(btn) {
    document.querySelectorAll('.segment').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

let practice = {items: [], index: 0, revealed: false, saving: false, answer: ''};
let practiceLoadId = 0;

async function loadPractice() {
    const loadId = ++practiceLoadId;
    try {
        const response = await fetch('/api/memories/practice');
        if (!response.ok) throw new Error('Practice request failed');
        const data = await response.json();
        if (currentMemoryTab !== 'practice' || loadId !== practiceLoadId) return;
        practice = {items: data.memories, index: 0, revealed: false, saving: false, answer: ''};
        renderPractice();
    } catch (error) {
        if (currentMemoryTab === 'practice' && loadId === practiceLoadId) {
            document.getElementById('memoryListBody').innerHTML = '<p role="alert">복습을 불러오지 못했어요.</p><button class="text-action" onclick="loadPractice()">다시 시도</button>';
        }
    }
}

function renderPractice() {
    if (currentMemoryTab !== 'practice') return;
    const body = document.getElementById('memoryListBody');
    const item = practice.items[practice.index];
    if (!item) {
        body.innerHTML = `<div class="practice-card"><h3>${practice.items.length ? '오늘의 복습을 마쳤어요' : '지금 복습할 표현이 없어요'}</h3>
            <p>어려웠던 표현은 하루 뒤, 기억한 표현은 일주일 뒤에 다시 연습해요.</p>
            <button class="text-action" onclick="switchMemoryTab('errors')">오답 노트 보기</button></div>`;
        return;
    }
    body.innerHTML = `<div class="practice-card">
        <p class="practice-progress">오늘의 복습 ${practice.index + 1} / ${practice.items.length}</p>
        <h3>이 문장을 자연스럽게 고쳐 볼까요?</h3>
        <p class="practice-original" lang="ja">${escapeHTML(item.original_text || '')}</p>
        <label for="practiceAnswer">내가 고친 문장</label>
        <textarea id="practiceAnswer" lang="ja" rows="3" placeholder="일본어로 써 보세요" ${practice.revealed ? 'readonly' : ''}>${escapeHTML(practice.answer)}</textarea>
        ${practice.revealed ? `<div class="practice-solution"><p lang="ja">${escapeHTML(item.corrected_text)}</p><p>${escapeHTML(item.explanation || '')}</p></div>
            <p>예시와 표현이 달라도 괜찮아요. 직접 비교하고 골라 주세요.</p>
            <div class="practice-actions"><button class="text-action" ${practice.saving ? 'disabled' : ''} onclick="savePracticeReview(false)">아직 어려워요</button>
            <button class="text-action" ${practice.saving ? 'disabled' : ''} onclick="savePracticeReview(true)">기억했어요</button></div>` :
            '<button class="text-action" onclick="revealPractice()">정답과 비교하기</button>'}
        <p id="practiceError" role="alert"></p>
    </div>`;
}

function revealPractice() {
    practice.answer = document.getElementById('practiceAnswer').value;
    practice.revealed = true;
    renderPractice();
}

async function savePracticeReview(remembered) {
    const active = practice;
    const item = active.items[active.index];
    if (!item || !active.revealed || active.saving) return;
    active.saving = true;
    renderPractice();
    try {
        const response = await fetch(`/api/memories/${item.id}/review`, {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({remembered})
        });
        if (!response.ok) throw new Error('Review save failed');
        active.index++;
        active.answer = '';
        active.revealed = false;
    } catch (error) {
        active.error = '복습 기록을 저장하지 못했어요. 다시 눌러 주세요.';
    } finally {
        active.saving = false;
        if (practice === active) {
            renderPractice();
            if (active.error && currentMemoryTab === 'practice') document.getElementById('practiceError').textContent = active.error;
            delete active.error;
        }
    }
}


function scenarioName(prompt) {
    return prompt.name.replace(/^[^가-힣A-Za-z0-9]+/, '').replace(/\s*\([^)]*\)/g, '').trim();
}

function uiIcon(name) {
    const paths = {
        like: '<path d="M7 10v10H3V10h4Zm0 0 5-7c2 0 2 3 1 6h6c2 0 2 2 2 3l-2 7H7"/>',
        dislike: '<path d="M7 14V4H3v10h4Zm0 0 5 7c2 0 2-3 1-6h6c2 0 2-2 2-3l-2-7H7"/>',
        trash: '<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>'
    };
    return `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name] || ''}</svg>`;
}

async function openLearning(tabName) {
    document.getElementById('memoryModalBackdrop').classList.add('show');
    syncOverlayFocus();
    switchMemoryTab(tabName);
}

function useStarter(text) {
    if (state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    messageInput.value = text;
    autoResize();
    messageInput.focus();
}

async function newConversation() {
    if (state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    if (!await startNewSession(false)) {
        document.getElementById('sceneError').textContent = '새 대화를 시작하지 못했어요. 잠시 후 다시 눌러 주세요.';
    } else {
        document.getElementById('sceneError').textContent = '';
    }
}

async function startScenario(id) {
    if (state.isLoading || state.isSavingSettings || state.isSessionTransition) return;
    const error = document.getElementById('sceneError');
    const prompt = mcpPrompts.find(item => item.id === id);
    if (!prompt) {
        error.textContent = '상황 목록을 준비하지 못했어요. 설정을 열어 다시 확인해 주세요.';
        return;
    }
    error.textContent = '';
    const args = Object.fromEntries((prompt.arguments || []).map(arg => [arg.name, arg.default || '']));
    if (!await startNewSession(false, {...state.settings, roleplayId: id, roleplayArgs: args})) {
        error.textContent = '대화를 시작하지 못했어요. 잠시 후 다시 눌러 주세요.';
        return;
    }
    applySettingsToUI();
    try { localStorage.setItem('nihongoSettings', JSON.stringify(state.settings)); }
    catch (err) { console.error('Settings cache write failed:', err); }
    document.getElementById('conversationPanel').scrollIntoView({block: 'start', behavior: 'auto'});
    messageInput.focus({preventScroll: true});
}


let overlayFocusOrigin = null;

function syncOverlayFocus() {
    const overlay = document.querySelector('.modal-overlay.show .modal, .drawer.active');
    if (overlay && typeof overlay.querySelector === 'function') {
        overlayFocusOrigin = overlayFocusOrigin || document.activeElement;
        overlay.querySelector('button, input, textarea')?.focus();
    } else if (!overlay && overlayFocusOrigin) {
        overlayFocusOrigin.focus?.();
        overlayFocusOrigin = null;
    }
}

document.addEventListener('keydown', event => {
    const overlay = document.querySelector('.modal-overlay.show .modal, .drawer.active');
    if (!overlay) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        overlay.querySelector('.close-btn')?.click();
    } else if (event.key === 'Tab') {
        const controls = [...overlay.querySelectorAll('button:not(:disabled), input, textarea, a[href]')]
            .filter(element => element.getClientRects().length > 0);
        if (!controls.length) return;
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault(); first.focus();
        }
    }
});
