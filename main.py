from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from langsmith import traceable
import os
import time
from dotenv import load_dotenv

from security_filters import redact_sensitive_output, scan_prompt_injection
from rag_access import rag_access_configured
from mcp_prompts import list_mcp_prompts, get_mcp_prompt_instruction
from database import (
    init_db, create_session, get_all_sessions, get_session, delete_session,
    save_message, get_session_messages, save_user_memory, get_user_memories
)
import uuid

load_dotenv()

app = FastAPI(title="니혼고챗", description="일본어 학습 채팅 앱") #웹 문서 페이지 맨 위에 표시되는 문구


@app.on_event("startup")
def on_startup():
    init_db()


# 정적 파일 및 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class CreateSessionRequest(BaseModel):
    title: str = "새 대화"
    partner_name: str = "유키"
    difficulty: str = "beginner"
    topic: str = "free"
    roleplay_id: str | None = None


class ChatRequest(BaseModel):
    message: str
    history: list = []
    api_key: str
    partner_name: str = "유키"
    difficulty: str = "beginner"
    topic: str = "free"
    roleplay_id: str | None = None
    roleplay_args: dict | None = None
    session_id: str | None = None


class TranslateRequest(BaseModel):
    text: str
    api_key: str


class MCPGetPromptRequest(BaseModel):
    id: str
    arguments: dict = {}


def _assert_no_prompt_injection(text: str) -> None:
    code = scan_prompt_injection(text)
    if code:
        raise HTTPException(
            status_code=400,
            detail={"error": "prompt_injection_suspected", "code": code},
        )


def _scan_history_for_injection(history: list) -> None:
    for item in history:
        if not isinstance(item, dict):
            continue
        if item.get("role") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            _assert_no_prompt_injection(content)


def get_system_prompt(partner_name: str, difficulty: str, topic: str, roleplay_id: str | None = None, roleplay_args: dict | None = None) -> str:
    difficulty_prompt = DIFFICULTY_PROMPTS.get(difficulty, DIFFICULTY_PROMPTS["beginner"])
    topic_prompt = TOPIC_PROMPTS.get(topic, TOPIC_PROMPTS["free"])
    
    roleplay_instruction = ""
    if roleplay_id:
        rp_text = get_mcp_prompt_instruction(roleplay_id, roleplay_args)
        if rp_text:
            roleplay_instruction = f"\n\n[Active Roleplay Scenario (MCP Prompt)]\n{rp_text}"
    
    memory_instruction = ""
    memories = get_user_memories(limit=5)
    if memories:
        mem_lines = []
        for m in memories:
            mem_lines.append(f"- Correction: {m['original_text']} -> {m['corrected_text']} ({m['explanation']})")
        memory_instruction = f"\n\n[Learner's Past Weaknesses & Memory Notes]\nThe learner previously made these mistakes. If natural, gently help them practice these grammar points:\n" + "\n".join(mem_lines)

    base_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        partner_name=partner_name,
        difficulty_prompt=difficulty_prompt,
        topic_prompt=topic_prompt
    )
    
    return base_prompt + roleplay_instruction + memory_instruction


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/rag/status")
async def rag_status():
    """RAG 서버 토큰 설정 여부. 실제 retrieve 시 `rag_access.assert_rag_collection_access` 사용."""
    return {"rag_configured": rag_access_configured()}


@app.get("/api/mcp/prompts")
async def mcp_prompts_list():
    """MCP Prompts 표준 규격에 따라 등록된 상황별 롤플레잉 프롬프트 목록 반환"""
    return {"prompts": list_mcp_prompts()}


@app.post("/api/mcp/prompts/get")
async def mcp_prompts_get(req: MCPGetPromptRequest):
    """특정 MCP Prompt ID와 arguments를 받아 렌더링된 프롬프트 반환"""
    instruction = get_mcp_prompt_instruction(req.id, req.arguments)
    if not instruction:
        raise HTTPException(status_code=440, detail="요청한 MCP Prompt를 찾을 수 없습니다.")
    return {"prompt_id": req.id, "instruction": instruction}


# --- Sessions & Memories APIs ---

@app.get("/api/sessions")
async def list_sessions():
    """저장된 전체 대화 세션 목록 반환"""
    return {"sessions": get_all_sessions()}


@app.post("/api/sessions")
async def api_create_session(req: CreateSessionRequest):
    """새 대화 세션 생성"""
    sess_id = str(uuid.uuid4())
    session_data = create_session(
        session_id=sess_id,
        title=req.title,
        partner_name=req.partner_name,
        difficulty=req.difficulty,
        topic=req.topic,
        roleplay_id=req.roleplay_id
    )
    return {"session": session_data}


@app.get("/api/sessions/{session_id}")
async def get_session_detail(session_id: str):
    """특정 세션 정보 및 메시지 이력 반환"""
    session = get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    messages = get_session_messages(session_id)
    return {"session": session, "messages": messages}


@app.delete("/api/sessions/{session_id}")
async def api_delete_session(session_id: str):
    """특정 세션 삭제"""
    deleted = delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="삭제할 세션을 찾을 수 없습니다.")
    return {"status": "deleted", "session_id": session_id}


@app.get("/api/memories")
async def api_list_memories():
    """학습자의 오답 노트 및 개인화 메모리 목록 반환"""
    return {"memories": get_user_memories(limit=30)}


# 구글 웹 검색 RAG 트리거 전용 키워드 (기본값 OFF, 명확한 뉴스/유행/트렌드 키워드에서만 켜짐)
STRICT_SEARCH_KEYWORDS = [
    "뉴스", "유행", "트렌드", "실시간", "구글 검색", "웹 검색", "핫이슈",
    "ニュース", "トレンド", "リアルタイム", "話題", "流行り"
]


def _needs_web_search(message: str) -> bool:
    msg = message.lower()
    return any(keyword in msg for keyword in STRICT_SEARCH_KEYWORDS)


@app.post("/api/chat")
@traceable(name="gemini_chat")
async def chat(req: ChatRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.message)
    _scan_history_for_injection(req.history)

    try:
        client = genai.Client(api_key=req.api_key)
        
        sys_prompt = get_system_prompt(
            req.partner_name, 
            req.difficulty, 
            req.topic, 
            req.roleplay_id, 
            req.roleplay_args
        )
        
        contents = []
        for item in req.history[-10:]:
            role = "user" if item.get("role") == "user" else "model"
            content = item.get("content", "")
            if content:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
        
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=req.message)]))
        
        start_t = time.time()
        use_search = _needs_web_search(req.message)
        print(f"[Chat API START] Message: '{req.message}' | Search Triggered: {use_search}")
        
        if use_search:
            config_search = types.GenerateContentConfig(
                system_instruction=sys_prompt,
                temperature=0.8,
                max_output_tokens=1000,
                tools=[types.Tool(google_search=types.GoogleSearch())]
            )
            try:
                response = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=contents,
                    config=config_search
                )
            except Exception as search_err:
                print(f"[Chat API] Search failed ({search_err}). Falling back to basic mode.")
                config_basic = types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    temperature=0.8,
                    max_output_tokens=1000
                )
                response = client.models.generate_content(
                    model="gemini-3.5-flash",
                    contents=contents,
                    config=config_basic
                )
        else:
            config_basic = types.GenerateContentConfig(
                system_instruction=sys_prompt,
                temperature=0.8,
                max_output_tokens=1000
            )
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents,
                config=config_basic
            )
        
        elapsed = time.time() - start_t
        print(f"[Chat API END] Completed in {elapsed:.2f} seconds.")
        raw = response.text or ""
        clean_res = redact_sensitive_output(raw)
        
        # 세션 ID가 제공되었다면 유저 메시지 및 AI 답장 DB 저장
        if req.session_id:
            user_msg_id = f"usr_{int(time.time() * 1000)}"
            assistant_msg_id = f"ast_{int(time.time() * 1000) + 1}"
            save_message(user_msg_id, req.session_id, "user", req.message)
            save_message(assistant_msg_id, req.session_id, "assistant", clean_res)

        return {"response": clean_res}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/translate")
@traceable(name="gemini_translate")
async def translate(req: TranslateRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        start_t = time.time()
        client = genai.Client(api_key=req.api_key)
        
        config = types.GenerateContentConfig(
            system_instruction=TRANSLATE_PROMPT,
            temperature=0.3,
            max_output_tokens=500
        )
        
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=req.text,
            config=config
        )
        
        elapsed = time.time() - start_t
        print(f"[Translate API END] Completed in {elapsed:.2f} seconds.")
        raw = response.text or ""
        return {"translation": redact_sensitive_output(raw)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/furigana")
@traceable(name="gemini_furigana")
async def furigana(req: TranslateRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        start_t = time.time()
        client = genai.Client(api_key=req.api_key)
        
        config = types.GenerateContentConfig(
            system_instruction=FURIGANA_PROMPT,
            temperature=0.1,
            max_output_tokens=500
        )
        
        response = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=req.text,
            config=config
        )
        
        elapsed = time.time() - start_t
        print(f"[Furigana API END] Completed in {elapsed:.2f} seconds.")
        raw = response.text or ""
        return {"furigana": redact_sensitive_output(raw)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# PROMPT SETTINGS
# ============================================================

# Difficulty Prompts
BEGINNER_PROMPT = """
# Difficulty: Beginner
# Persona: You are a Japanese friend of a Korean person learning Japanese. Please speak in easy Japanese at a kindergarten level.
- Use simple words and short sentences (1-2 sentences).
- Use polite form (です・ます form).
- Use basic kanji and hiragana.
"""

INTERMEDIATE_PROMPT = """
# Difficulty: Intermediate
# Persona: You are a Japanese friend of a Korean person learning Japanese. Please speak in natural Japanese at a middle school level.
- Use everyday conversational expressions (2-3 sentences).
- Use common kanji appropriately.
- Use polite and casual speech depending on the context.
- Gently guide grammar mistakes to natural expressions.
"""

ADVANCED_PROMPT = """
# Difficulty: Advanced
# Persona: You are a Japanese friend of a Korean person learning Japanese. Please speak in natural and sophisticated Japanese at a high school/adult level.
- Use native-level expressions, idioms, and slang.
- Include business expressions and honorifics (敬語) when appropriate.
- Suggest subtle natural nuances.
"""

DIFFICULTY_PROMPTS = {
    "beginner": BEGINNER_PROMPT,
    "intermediate": INTERMEDIATE_PROMPT,
    "advanced": ADVANCED_PROMPT
}

# --------------------------------------------------------------------------------------

# Topic Prompts
TOPIC_PROMPTS = {
    "free": "Feel free to talk about anything.",
    "dailyLife": "Talk about daily life. (From waking up in the morning to going to bed)",
    "travel": "Talk about traveling in Japan. (Tourist spots, transportation, accommodation, etc.)",
    "food": "Talk about Japanese food and cooking.",
    "culture": "Talk about Japanese culture. (Festivals, customs, traditions, etc.)",
    "business": "Have a conversation in business Japanese. (Meetings, phone calls, emails, etc.)",
    "anime": "Talk about anime and manga."
}

# --------------------------------------------------------------------------------------

# System Prompt Template
SYSTEM_PROMPT_TEMPLATE = """Your name is "{partner_name}". You are a Japanese person in your 20s living in Japan.
{difficulty_prompt}

Conversation Topic: {topic_prompt}

CRITICAL FORMATTING RULE:
- NEVER include bracketed furigana/readings like 過ご(すご)す or 今日(きょう) in your main conversation response!
- Output ONLY clean, natural Japanese text without any parenthetical readings.

Important Rules:
- Have a natural conversation like a friend with a Korean Japanese learner
- Occasionally ask questions to keep the conversation going
- If the other person's Japanese is incorrect, naturally respond with the correct expression
- Use emojis moderately to create a friendly atmosphere
- Always respond in Japanese"""

# --------------------------------------------------------------------------------------

# Translation Prompt
TRANSLATE_PROMPT = """주어진 일본어 문장을 자연스러운 한국어로 번역하세요.
중요 지침:
- 영어 설명, 부연 해설, 서식 표식(*, Sentence 등) 없이 오직 한국어 번역 결과 문장만 그대로 출력하세요.
- 예: "안녕하세요. 오늘 날씨가 참 좋네요." """

# --------------------------------------------------------------------------------------

# Furigana Prompt
FURIGANA_PROMPT = """주어진 일본어 문장의 한자 뒤에 괄호로 히라가나 읽는 법(후리가나)을 표기하세요.
중요 지침:
- 영문 문법 설명, 영어 주석, 용법 비교 코멘트("is acceptable", "usually" 등), 피드백 표기를 절대로 출력하지 마세요!
- 오직 올바른 후리가나가 달린 일본어 문장 결과만 그대로 출력하세요.
- 형식: 한자(히라가나)
- 예: 今日(きょう)は天気(てんき)がいいですね。"""

# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
