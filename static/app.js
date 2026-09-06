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

    let html = '';
    mcpPrompts.forEach(prompt => {
        const isActive = prompt.id === state.settings.roleplayId || (!state.settings.roleplayId && prompt.id === null);
        html += `
            <div class="roleplay-card ${isActive ? 'active' : ''}" onclick="selectRoleplay(this, ${prompt.id ? `'${prompt.id}'` : 'null'})">
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
    
    if (difficultyStatus) {
        difficultyStatus.textContent = '📚 ' + DIFFICULTY_NAMES[state.settings.difficulty];
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

        state.settings = {
            apiKey: '',
            partnerName: partnerNameEl ? partnerNameEl.value : '유키',
            difficulty: newDifficulty,
            topic: 'free',
            roleplayId: state.settings ? state.settings.roleplayId : null,
            roleplayArgs: roleplayArgs,
            showTranslation: showTransEl ? showTransEl.checked : true,
            showFurigana: showFuriEl ? showFuriEl.checked : true
        };
        
        localStorage.setItem('nihongoSettings', JSON.stringify(state.settings));
        
        const settingsChanged = (
            prevDifficulty !== newDifficulty ||
            prevRoleplayId !== state.settings.roleplayId ||
            JSON.stringify(prevRoleplayArgs) !== JSON.stringify(roleplayArgs)
        );
        
        if (settingsChanged) {
            startNewSession(false);
        } else if (state.messages.length === 0) {
            addWelcomeMessage();
        }
        
        updateStatusBar();
    } catch (err) {
        console.error('Error saving settings:', err);
    } finally {
        // 어떤 경우에도 저장 버튼 클릭 시 설정 모달 100% 닫기 보장
        const modal = document.getElementById('settingsModal');
        if (modal) {
            modal.classList.remove('show');
            modal.style.display = 'none';
            setTimeout(() => { modal.style.display = ''; }, 300);
        }
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

async function startNewSession(closeDrawer = true) {
    try {
        let title = `🎭 일반 대화 (${DIFFICULTY_NAMES[state.settings.difficulty] || '초급'})`;
        if (state.settings.roleplayId) {
            const rp = mcpPrompts.find(p => p.id === state.settings.roleplayId);
            if (rp) {
                title = `🎭 ${rp.name} (${DIFFICULTY_NAMES[state.settings.difficulty] || '초급'})`;
            }
        }
        
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
            sessionStorage.setItem('nihongoActiveSessionId', newSess.session_id);
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
            sessionStorage.setItem('nihongoActiveSessionId', sessionId);
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

let currentMemoryTab = 'errors';

function switchMemoryTab(tabName) {
    currentMemoryTab = tabName;
    const btnErrors = document.getElementById('tabErrorsBtn');
    const btnFacts = document.getElementById('tabFactsBtn');
    
    if (tabName === 'errors') {
        if (btnErrors) btnErrors.classList.add('active');
        if (btnFacts) btnFacts.classList.remove('active');
    } else {
        if (btnFacts) btnFacts.classList.add('active');
        if (btnErrors) btnErrors.classList.remove('active');
    }
    loadAndRenderMemories();
}

async function loadAndRenderMemories() {
    const body = document.getElementById('memoryListBody');
    if (!body) return;
    body.innerHTML = '<p style="text-align:center; color: var(--text-muted); padding: 20px;">로딩 중...</p>';
    
    if (currentMemoryTab === 'errors') {
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
    } else {
        // 장기 기억 프로필 탭
        try {
            const res = await fetch('/api/facts');
            if (res.ok) {
                const data = await res.json();
                const facts = data.facts || [];
                const summaries = data.summaries || [];
                
                if (facts.length === 0 && summaries.length === 0) {
                    body.innerHTML = `
                        <div class="memory-card" style="border-left-color: #27ae60;">
                            <div class="memory-card-header">
                                <span class="memory-badge" style="background: #e8f8f5; color: #27ae60;">AI Agent Long-Term Memory</span>
                            </div>
                            <div class="memory-corrected" style="color: #2c3e50;">📌 대화 맥락 & 취향 자동 요약 대기 중</div>
                            <div class="memory-explanation" style="line-height: 1.6;">
                                대화가 6건 이상 진행되면 백그라운드 AI가 대화 내용을 분석하여 100% 한국어로 2~3줄 요약문과 학습자 프로필 카드를 여기에 실시간 적재합니다! 🧠
                            </div>
                        </div>
                    `;
                    return;
                }
                
                let html = '';
                
                if (facts.length > 0) {
                    html += facts.map(f => `
                        <div class="memory-card" style="border-left-color: #3498db;">
                            <div class="memory-card-header">
                                <span class="memory-badge" style="background: #ebf5fb; color: #2980b9;">Learner Fact</span>
                                <span>${new Date(f.updated_at).toLocaleDateString('ko-KR')}</span>
                            </div>
                            <div class="memory-corrected" style="color: #2c3e50;">💡 ${escapeHTML(f.fact_key || '')}</div>
                            <div class="memory-explanation">${escapeHTML(f.fact_value || '')}</div>
                        </div>
                    `).join('');
                }
                
                if (summaries.length > 0) {
                    html += summaries.map(s => `
                        <div class="memory-card" style="border-left-color: #27ae60;">
                            <div class="memory-card-header">
                                <span class="memory-badge" style="background: #e8f8f5; color: #27ae60;">Session Summary</span>
                                <span>${new Date(s.updated_at).toLocaleDateString('ko-KR')}</span>
                            </div>
                            <div class="memory-corrected" style="color: #2c3e50;">📜 ${escapeHTML(s.title || '대화 세션 요약')}</div>
                            <div class="memory-explanation" style="line-height: 1.5;">${escapeHTML(s.summary || '')}</div>
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
            `こんにちは！私は${state.settings.partnerName}です。日本語の練習、一緒に頑張りましょう！😊`,
            `やあ！${state.settings.partnerName}だよ。今日は何を話そうか？🌸`,
            `はじめまして！${state.settings.partnerName}です。気軽に話しかけてね！✨`
        ];
        content = welcomeMessages[Math.floor(Math.random() * welcomeMessages.length)];
    }
    
    const message = {
        id: Date.now().toString(),
        role: 'assistant',
        content: content,
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
                    <div class="message-footer-bar">
                        ${canShowDetails ? '<span class="tap-hint">클릭하여 번역 보기</span>' : ''}
                        <div class="feedback-bar" id="feedback-bar-${message.id}">
                            <button class="feedback-btn like-btn ${message.feedback_rating === 1 ? 'active' : ''}" onclick="submitFeedback(event, '${message.id}', 1)" title="도움이 되었어요">👍</button>
                            <button class="feedback-btn dislike-btn ${message.feedback_rating === -1 ? 'active' : ''}" onclick="submitFeedback(event, '${message.id}', -1)" title="어색하거나 피하고 싶은 답장이에요">👎</button>
                        </div>
                    </div>
                    <span class="timestamp">${time}</span>
                </div>
            </div>
        `;
    }
}

async function submitFeedback(event, messageId, rating) {
    if (event) event.stopPropagation();
    try {
        const feedbackBtnBar = document.getElementById(`feedback-bar-${messageId}`);
        if (feedbackBtnBar) {
            feedbackBtnBar.querySelectorAll('.feedback-btn').forEach(btn => btn.classList.remove('active'));
            const targetBtn = rating === 1 ? feedbackBtnBar.querySelector('.like-btn') : feedbackBtnBar.querySelector('.dislike-btn');
            if (targetBtn) targetBtn.classList.add('active');
        }
        
        let feedbackText = null;

        // DB에 즉시 100% 피드백 저장 전송
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
        
        if (res.ok) {
            console.log(`[Feedback System] Feedback ${rating} successfully recorded in DB for message ${messageId}`);
        }
    } catch (e) {
        console.error('Submit feedback failed:', e);
    }
}

// HTML 이스케이프
function escapeHTML(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function isValidFurigana(reading, source) {
    if (!reading || /[A-Za-z]/.test(reading)) return false;
    const hasKanji = /[\u3400-\u9FFF々〆ヶ]/.test(source || '');
    if (!hasKanji) return true;
    return /\([\u3040-\u309Fー]+\)/.test(reading);
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
    const needsFurigana = state.settings.showFurigana && !isValidFurigana(message.furigana, message.content);
    
    if (needsTranslation || needsFurigana) {
        // 로딩 표시
        details.innerHTML = '<div class="detail-section"><div class="detail-text">로딩 중...</div></div>';
        details.classList.add('show');
        
        const tasks = [];

        if (needsTranslation) {
            tasks.push(
                fetch('/api/translate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message.content, api_key: state.settings.apiKey || '' })
                })
                .then(res => res.ok ? res.json() : null)
                .then(data => { if (data) message.translation = data.translation; })
                .catch(e => console.error('Translation failed:', e))
            );
        }

        if (needsFurigana) {
            tasks.push(
                fetch('/api/furigana', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text: message.content, api_key: state.settings.apiKey || '' })
                })
                .then(res => res.ok ? res.json() : null)
                .then(data => {
                    if (data && isValidFurigana(data.furigana, message.content)) {
                        message.furigana = data.furigana;
                    } else {
                        delete message.furigana;
                    }
                })
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
    setTimeout(() => {
        messageInput.value = '';
        messageInput.style.height = 'auto';
    }, 0);
    
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
            id: `ast_${Date.now() + 1}`,
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

// 엔터 키 처리 (한글/일본어 IME 글자 조합 중복 입력 방지)
function handleKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        if (event.isComposing) return;
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


function selectDifficulty(btn) {
    document.querySelectorAll('.segment').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}

function selectTopic(btn) {
    document.querySelectorAll('.topic-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
}