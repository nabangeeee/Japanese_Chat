// 상태 관리
let state = {
    messages: [],
    sessions: [],
    currentSessionId: null,
    memories: [],
    isLoading: false,
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

// 난이도/주제 한글 이름 매핑
const DIFFICULTY_NAMES = {
    'beginner': '초급',
    'intermediate': '중급',
    'advanced': '고급'
};

const TOPIC_NAMES = {
    'free': '자유 대화',
    'dailyLife': '일상생활',
    'travel': '여행',
    'food': '음식',
    'culture': '문화',
    'business': '비즈니스',
    'anime': '애니/만화'
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
        }
    } catch (e) {
        console.error('MCP Prompts 로드 실패:', e);
    }
}

// MCP Prompts UI 동적 렌더링
function renderMcpPromptsUI() {
    const container = document.getElementById('roleplayContainer');
    if (!container) return;

    let html = `
        <div class="roleplay-card ${!state.settings.roleplayId ? 'active' : ''}" data-id="" onclick="selectRoleplay(this, null)">
            <div class="rp-card-header">
                <span class="rp-card-title">💬 일반 대화</span>
                <span class="rp-card-badge">기본</span>
            </div>
            <p class="rp-card-desc">특정 롤플레잉 없이 자유롭게 대화합니다.</p>
        </div>
    `;

    mcpPrompts.forEach(prompt => {
        const isActive = state.settings.roleplayId === prompt.id;
        html += `
            <div class="roleplay-card ${isActive ? 'active' : ''}" data-id="${prompt.id}" onclick="selectRoleplay(this, '${prompt.id}')">
                <div class="rp-card-header">
                    <span class="rp-card-title">${escapeHTML(prompt.name)}</span>
                    <span class="rp-card-badge">${escapeHTML(prompt.category)}</span>
                </div>
                <p class="rp-card-desc">${escapeHTML(prompt.description)}</p>
            </div>
        `;
    });

    container.innerHTML = html;
    renderRoleplayArgsForm();
}

function selectRoleplay(element, promptId) {
    document.querySelectorAll('.roleplay-card').forEach(card => card.classList.remove('active'));
    element.classList.add('active');
    
    state.settings.roleplayId = promptId;
    renderRoleplayArgsForm();
}

function renderRoleplayArgsForm() {
    const argsContainer = document.getElementById('roleplayArgsContainer');
    if (!argsContainer) return;

    const currentPrompt = mcpPrompts.find(p => p.id === state.settings.roleplayId);
    if (!currentPrompt || !currentPrompt.arguments || currentPrompt.arguments.length === 0) {
        argsContainer.style.display = 'none';
        argsContainer.innerHTML = '';
        return;
    }

    argsContainer.style.display = 'block';
    let html = `<div class="rp-args-title">⚙️ ${currentPrompt.name} 세부 옵션</div>`;

    currentPrompt.arguments.forEach(arg => {
        const val = state.settings.roleplayArgs[arg.name] || arg.default || '';
        html += `
            <div class="rp-arg-row">
                <label class="rp-arg-label">${escapeHTML(arg.description || arg.name)}</label>
                <input type="text" class="rp-arg-input" data-arg-name="${arg.name}" value="${escapeHTML(val)}" placeholder="${escapeHTML(arg.default || '')}">
            </div>
        `;
    });

    argsContainer.innerHTML = html;
}

// 설정 로드
function loadSettings() {
    const saved = localStorage.getItem('nihongoSettings');
    if (saved) {
        state.settings = { ...state.settings, ...JSON.parse(saved) };
    }
    applySettingsToUI();
}

// 설정 UI에 적용
function applySettingsToUI() {
    document.getElementById('apiKey').value = state.settings.apiKey;
    document.getElementById('partnerName').value = state.settings.partnerName;
    document.getElementById('showTranslation').checked = state.settings.showTranslation;
    document.getElementById('showFurigana').checked = state.settings.showFurigana;
    
    // 난이도 버튼
    document.querySelectorAll('.segment').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.value === state.settings.difficulty);
    });
    
    // 주제 버튼
    document.querySelectorAll('.topic-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.value === state.settings.topic);
    });
    
    // MCP Prompts 재렌더링
    renderMcpPromptsUI();

    // 상태 바 업데이트
    updateStatusBar();
}

// 상태 바 업데이트
function updateStatusBar() {
    const difficultyStatus = document.getElementById('difficultyStatus');
    const topicStatus = document.getElementById('topicStatus');
    const roleplayStatus = document.getElementById('roleplayStatus');
    
    if (difficultyStatus) {
        difficultyStatus.textContent = '📚 ' + DIFFICULTY_NAMES[state.settings.difficulty];
    }
    if (topicStatus) {
        topicStatus.textContent = '💬 ' + TOPIC_NAMES[state.settings.topic];
    }
    if (roleplayStatus) {
        if (state.settings.roleplayId) {
            const promptObj = mcpPrompts.find(p => p.id === state.settings.roleplayId);
            roleplayStatus.textContent = promptObj ? promptObj.name.split(' ')[0] + ' 롤플레잉' : '🎭 롤플레잉 중';
        } else {
            roleplayStatus.textContent = '🎭 일반 대화';
        }
    }
}

// 설정 저장
function saveSettings() {
    // 이전 설정 저장
    const prevDifficulty = state.settings.difficulty;
    const prevTopic = state.settings.topic;
    const prevRoleplayId = state.settings.roleplayId;
    
    // 새 설정 가져오기 (모달 내의 버튼 및 input에서)
    const activeSegment = document.querySelector('#settingsModal .segment.active');
    const activeTopic = document.querySelector('#settingsModal .topic-btn.active');
    
    const newDifficulty = activeSegment ? activeSegment.dataset.value : 'beginner';
    const newTopic = activeTopic ? activeTopic.dataset.value : 'free';
    
    // 롤플레잉 args 수집
    const roleplayArgs = {};
    document.querySelectorAll('.rp-arg-input').forEach(input => {
        const argName = input.dataset.argName;
        if (argName) {
            roleplayArgs[argName] = input.value.trim();
        }
    });

    state.settings = {
        apiKey: document.getElementById('apiKey').value,
        partnerName: document.getElementById('partnerName').value || '유키',
        difficulty: newDifficulty,
        topic: newTopic,
        roleplayId: state.settings.roleplayId || null,
        roleplayArgs: roleplayArgs,
        showTranslation: document.getElementById('showTranslation').checked,
        showFurigana: document.getElementById('showFurigana').checked
    };
    
    // localStorage에 저장
    localStorage.setItem('nihongoSettings', JSON.stringify(state.settings));
    
    // 난이도, 주제, 롤플레잉이 바뀌면 이전 세션은 DB에 안전 보존하고 새로운 세션 생성
    const settingsChanged = (prevDifficulty !== newDifficulty || prevTopic !== newTopic || prevRoleplayId !== state.settings.roleplayId);
    
    if (settingsChanged) {
        startNewSession(false);
    } else if (state.messages.length === 0) {
        addWelcomeMessage();
    }
    
    // 상태 바 업데이트
    updateStatusBar();
    
    // 모달 닫기
    toggleSettings();
}

// --- DB SESSION & MEMORY MANAGEMENT ---

async function initSessionSystem() {
    try {
        const res = await fetch('/api/sessions');
        if (res.ok) {
            const data = await res.json();
            state.sessions = data.sessions || [];
            
            if (state.sessions.length > 0) {
                await switchSession(state.sessions[0].session_id, false);
            } else {
                await startNewSession(false);
            }
        }
    } catch (e) {
        console.error('Session init failed:', e);
        loadMessages();
    }
}

async function startNewSession(closeDrawer = true) {
    try {
        const title = `${TOPIC_NAMES[state.settings.topic] || '자유 대화'} (${DIFFICULTY_NAMES[state.settings.difficulty] || '초급'})`;
        const res = await fetch('/api/sessions', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                title: title,
                partner_name: state.settings.partnerName,
                difficulty: state.settings.difficulty,
                topic: state.settings.topic,
                roleplay_id: state.settings.roleplayId
            })
        });
        if (res.ok) {
            const data = await res.json();
            const newSess = data.session;
            state.sessions.unshift(newSess);
            state.currentSessionId = newSess.session_id;
            state.messages = [];
            
            addWelcomeMessage();
            renderSessionList();
            if (closeDrawer) toggleSessionDrawer();
        }
    } catch (e) {
        console.error('Create session failed:', e);
    }
}

async function switchSession(sessionId, closeDrawer = true) {
    try {
        const res = await fetch(`/api/sessions/${sessionId}`);
        if (res.ok) {
            const data = await res.json();
            state.currentSessionId = sessionId;
            state.messages = data.messages || [];
            
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
    }
}

async function deleteSessionItem(event, sessionId) {
    event.stopPropagation();
    if (!confirm('이 대화 세션을 삭제하시겠습니까?')) return;
    try {
        const res = await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
        if (res.ok) {
            state.sessions = state.sessions.filter(s => s.session_id !== sessionId);
            if (state.currentSessionId === sessionId) {
                if (state.sessions.length > 0) {
                    await switchSession(state.sessions[0].session_id, false);
                } else {
                    await startNewSession(false);
                }
            } else {
                renderSessionList();
            }
        }
    } catch (e) {
        console.error('Delete session failed:', e);
    }
}

function toggleSessionDrawer() {
    const backdrop = document.getElementById('drawerBackdrop');
    const drawer = document.getElementById('sessionDrawer');
    if (!backdrop || !drawer) return;

    const isActive = drawer.classList.contains('active');
    if (isActive) {
        drawer.classList.remove('active');
        backdrop.classList.remove('active');
        setTimeout(() => {
            drawer.style.display = 'none';
            backdrop.style.display = 'none';
        }, 300);
    } else {
        renderSessionList();
        drawer.style.display = 'flex';
        backdrop.style.display = 'block';
        setTimeout(() => {
            drawer.classList.add('active');
            backdrop.classList.add('active');
        }, 10);
    }
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
                    <span class="session-item-sub">👤 ${escapeHTML(s.partner_name)} • ${dateStr}</span>
                </div>
                <button class="session-delete-btn" onclick="deleteSessionItem(event, '${s.session_id}')" title="삭제">🗑️</button>
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
    } else {
        modalBackdrop.classList.add('show');
        await loadAndRenderMemories();
    }
}

async function loadAndRenderMemories() {
    const body = document.getElementById('memoryListBody');
    if (!body) return;
    body.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px;">로딩 중...</p>';
    try {
        const res = await fetch('/api/memories');
        if (res.ok) {
            const data = await res.json();
            state.memories = data.memories || [];
            if (state.memories.length === 0) {
                body.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px; line-height: 1.6;">아직 축적된 오답 노어가 없습니다.<br>AI와 일본어로 회화하면서 틀린 문법이 있을 때 자동으로 노에 저장돼요! 💡</p>';
                return;
            }
            body.innerHTML = state.memories.map(m => `
                <div class="memory-card">
                    <div class="memory-card-header">
                        <span class="memory-badge">Grammar Error Note</span>
                        <span>${new Date(m.created_at).toLocaleDateString('ko-KR')}</span>
                    </div>
                    <div class="memory-original">❌ ${escapeHTML(m.original_text || '')}</div>
                    <div class="memory-corrected">✅ ${escapeHTML(m.corrected_text || '')}</div>
                    ${m.explanation ? `<div class="memory-explanation">💡 ${escapeHTML(m.explanation)}</div>` : ''}
                </div>
            `).join('');
        }
    } catch (e) {
        console.error('Load memories failed:', e);
        body.innerHTML = '<p style="text-align:center; color: red;">오답 노트를 불러오는데 실패했습니다.</p>';
    }
}

// 메시지 로드
function loadMessages() {
    const saved = localStorage.getItem('nihongoMessages');
    if (saved) {
        state.messages = JSON.parse(saved);
        renderMessages();
    } else {
        addWelcomeMessage();
    }
}

// 메시지 저장
function saveMessages() {
    localStorage.setItem('nihongoMessages', JSON.stringify(state.messages));
}

// 환영 메시지 추가
function addWelcomeMessage() {
    const welcomeMessages = [
        `こんにちは！私は${state.settings.partnerName}です。日本語の練習、一緒に頑張りましょう！😊`,
        `やあ！${state.settings.partnerName}だよ。今日は何を話そうか？🌸`,
        `はじめまして！${state.settings.partnerName}です。気軽に話しかけてね！✨`
    ];
    
    const message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)],
        timestamp: new Date().toISOString()
    };
    
    state.messages = [message];
    saveMessages();
    renderMessages();
}

// 메시지 렌더링
function renderMessages() {
    messagesContainer.innerHTML = state.messages.map(msg => createMessageHTML(msg)).join('');
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
                    <span class="timestamp">${time}</span>
                </div>
            </div>
        `;
    } else {
        const hasDetails = message.translation || message.furigana;
        const canShowDetails = state.settings.showTranslation || state.settings.showFurigana;
        
        return `
            <div class="message assistant">
                <div class="avatar">🇯🇵</div>
                <div class="bubble-container">
                    <div class="bubble" onclick="toggleDetails('${message.id}')">
                        ${escapeHTML(message.content)}
                        <div class="bubble-details" id="details-${message.id}" ${hasDetails ? '' : ''}>
                            ${message.furigana && state.settings.showFurigana ? `
                                <div class="detail-section">
                                    <div class="detail-label">📖 읽는 법</div>
                                    <div class="detail-text">${escapeHTML(message.furigana)}</div>
                                </div>
                            ` : ''}
                            ${message.translation && state.settings.showTranslation ? `
                                <div class="detail-section">
                                    <div class="detail-label">🇰🇷 번역</div>
                                    <div class="detail-text">${escapeHTML(message.translation)}</div>
                                </div>
                            ` : ''}
                        </div>
                    </div>
                    ${canShowDetails ? '<span class="tap-hint">클릭하여 번역 보기</span>' : ''}
                    <span class="timestamp">${time}</span>
                </div>
            </div>
        `;
    }
}

// HTML 이스케이프
function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// 상세 정보 토글
async function toggleDetails(messageId) {
    const details = document.getElementById(`details-${messageId}`);
    if (!details) return;
    
    // 이미 열려있으면 닫기
    if (details.classList.contains('show')) {
        details.classList.remove('show');
        return;
    }
    
    // 메시지 찾기
    const message = state.messages.find(m => m.id === messageId);
    if (!message) return;
    
    // 번역/후리가나가 없으면 가져오기
    const needsTranslation = state.settings.showTranslation && !message.translation;
    const needsFurigana = state.settings.showFurigana && !message.furigana;
    
    if (needsTranslation || needsFurigana) {
        // 로딩 표시
        details.innerHTML = '<div class="detail-section"><div class="detail-text">로딩 중...</div></div>';
        details.classList.add('show');
        
        const tasks = [];

        if (needsTranslation && state.settings.apiKey) {
            tasks.push(
                fetch('/api/translate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message.content, api_key: state.settings.apiKey })
                })
                .then(res => res.ok ? res.json() : null)
                .then(data => { if (data) message.translation = data.translation; })
                .catch(e => console.error('Translation failed:', e))
            );
        }

        if (needsFurigana && state.settings.apiKey) {
            tasks.push(
                fetch('/api/furigana', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message.content, api_key: state.settings.apiKey })
                })
                .then(res => res.ok ? res.json() : null)
                .then(data => { if (data) message.furigana = data.furigana; })
                .catch(e => console.error('Furigana failed:', e))
            );
        }
        
        // 100% 완전하게 완료될 때까지 기다림
        if (tasks.length > 0) {
            await Promise.all(tasks);
        }
        
        saveMessages();
        
        // 상세 정보 100% 완제품 업데이트
        details.innerHTML = `
            ${message.furigana && state.settings.showFurigana ? `
                <div class="detail-section">
                    <div class="detail-label">📖 읽는 법</div>
                    <div class="detail-text">${escapeHTML(message.furigana)}</div>
                </div>
            ` : ''}
            ${message.translation && state.settings.showTranslation ? `
                <div class="detail-section">
                    <div class="detail-label">🇰🇷 번역</div>
                    <div class="detail-text">${escapeHTML(message.translation)}</div>
                </div>
            ` : ''}
        `;
    } else {
        details.classList.add('show');
    }
}

// 타이핑 인디케이터
function showTypingIndicator() {
    const indicator = document.createElement('div');
    indicator.id = 'typingIndicator';
    indicator.className = 'typing-indicator';
    indicator.innerHTML = `
        <div class="avatar">🇯🇵</div>
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
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

// 메시지 전송
async function sendMessage() {
    const content = messageInput.value.trim();
    if (!content || state.isLoading) return;
    
    // 즉시 중복 전송 차단
    state.isLoading = true;
    sendBtn.disabled = true;
    
    if (!state.settings.apiKey) {
        alert('Google Gemini API 키를 설정해주세요.');
        toggleSettings();
        state.isLoading = false;
        sendBtn.disabled = false;
        return;
    }
    
    // 사용자 메시지 추가
    const userMessage = {
        id: Date.now().toString(),
        role: 'user',
        content: content,
        timestamp: new Date().toISOString()
    };
    
    state.messages.push(userMessage);
    saveMessages();
    renderMessages();
    
    messageInput.value = '';
    messageInput.style.height = 'auto';
    showTypingIndicator();
    
    try {
        // 대화 히스토리 구성
        const history = state.messages.slice(-10).map(msg => ({
            role: msg.role,
            content: msg.content
        }));
        
        const response = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: content,
                history: history.slice(0, -1),
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
        
        // AI 메시지 생성 후 화면에 100% 즉시 출력
        const assistantMessage = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: data.response,
            timestamp: new Date().toISOString()
        };
        
        state.messages.push(assistantMessage);
        saveMessages();
        
    } catch (error) {
        alert(error.message);
    } finally {
        state.isLoading = false;
        sendBtn.disabled = false;
        hideTypingIndicator();
        renderMessages();
    }
}

// 엔터 키 처리
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

// 대화 삭제
function clearChat() {
    if (confirm('모든 대화 내용을 삭제하시겠습니까?')) {
        state.messages = [];
        addWelcomeMessage();
    }
}

// 설정 모달
function toggleSettings() {
    settingsModal.classList.toggle('show');
}

function closeSettingsOnOverlay(event) {
    if (event.target === settingsModal) {
        toggleSettings();
    }
}

function toggleApiKeyVisibility() {
    const input = document.getElementById('apiKey');
    const icon = document.getElementById('eyeIcon');
    
    if (input.type === 'password') {
        input.type = 'text';
        icon.innerHTML = '<path d="M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>';
    } else {
        input.type = 'password';
        icon.innerHTML = '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>';
    }
}

function selectDifficulty(btn) {
    document.querySelectorAll('.segment').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function selectTopic(btn) {
    document.querySelectorAll('.topic-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

