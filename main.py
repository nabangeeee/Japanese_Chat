from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from langfuse import observe
import os
import time
from dotenv import load_dotenv

from security_filters import redact_sensitive_output, scan_prompt_injection
from rag_access import rag_access_configured
from mcp_prompts import list_mcp_prompts, get_mcp_prompt_instruction
from database import (
    init_db, create_session, get_all_sessions, get_session, delete_session,
    save_message, get_session_messages, save_user_memory, get_user_memories,
    save_session_summary, get_session_summary, save_user_fact, get_all_user_facts,
    get_recent_live_trends, save_message_feedback, get_negative_feedbacks
)
from hermes_client import is_hermes_available, summarize_session_with_hermes, extract_grammar_errors_with_hermes, analyze_feedback_with_hermes
from openclaw_collector import fetch_latest_japan_trends
from contextlib import asynccontextmanager
import uuid

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 앱 시작 시 실행 (Startup)
    init_db()
    yield
    # 앱 종료 시 필요한 작업이 있다면 여기에 작성


app = FastAPI(title="니혼고챗", description="일본어 학습 채팅 앱", lifespan=lifespan)


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


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str | None = None
    rating: int # 1 for like, -1 for dislike
    feedback_text: str | None = None
    api_key: str | None = None


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


def get_system_prompt(partner_name: str, difficulty: str, topic: str, roleplay_id: str | None = None, roleplay_args: dict | None = None, session_id: str | None = None) -> str:
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

    # 장기 메모리 요약본 및 유저 프로필 팩트 동적 주입
    long_term_instruction = ""
    if session_id:
        sess_summary = get_session_summary(session_id)
        facts = get_all_user_facts()
        
        lt_parts = []
        if sess_summary:
            lt_parts.append(f"Session Context Summary: {sess_summary}")
        if facts:
            fact_str = ", ".join([f"{f['fact_key']}={f['fact_value']}" for f in facts])
            lt_parts.append(f"Known Learner Profile/Facts: {fact_str}")
            
        if lt_parts:
            long_term_instruction = f"\n\n[Long-term Memory & Learner Context]\n" + "\n".join(lt_parts)

    # OpenClaw 실시간 일본 트렌드 이슈 주입
    trend_instruction = ""
    trends = get_recent_live_trends(limit=3)
    if trends:
        tr_lines = [f"- {t['title']}" for t in trends]
        trend_instruction = f"\n\n[OpenClaw Real-Time Japan Live Trends Context]\n" + "\n".join(tr_lines)

    # 유저 피드백 기반 금지/개선 규칙 동적 주입
    feedback_instruction = ""
    all_facts = get_all_user_facts()
    disliked_rules = [f["fact_value"] for f in all_facts if f["fact_key"].startswith("disliked_pattern_")]
    if disliked_rules:
        rule_lines = [f"- {r}" for r in disliked_rules[-3:]]
        feedback_instruction = f"\n\n[Hermes Self-Correction & Refinement Rules]\nThe Hermes Agent analyzed past user feedback/errors and extracted these refinement rules. STRICTLY FOLLOW THESE RULES:\n" + "\n".join(rule_lines)

    base_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        partner_name=partner_name,
        difficulty_prompt=difficulty_prompt,
        topic_prompt=topic_prompt
    )
    
    return base_prompt + roleplay_instruction + memory_instruction + long_term_instruction + trend_instruction + feedback_instruction


def _update_session_summary_background(api_key: str, session_id: str):
    """백그라운드에서 세션 대화 내역이 6건 이상일 때 대화 요약문 및 유저 팩트를 자동 추출하여 DB에 적재 (Hermes 우선 -> Gemini 폴백)"""
    try:
        messages = get_session_messages(session_id)
        if len(messages) < 6:
            return

        dialogue_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-14:]])
        
        # 1. Hermes 로컬 에이전트 가용 시 우선 처리 (비용 0원 & API 쿼터 아낌)
        if is_hermes_available():
            summary, facts = summarize_session_with_hermes(dialogue_text)
            if summary:
                save_session_summary(session_id, summary)
                print(f"[Hermes Agent Summary] Updated summary for session '{session_id}': {summary[:40]}...")
            for k, v in facts.items():
                save_user_fact(k, v)
            return

        # 2. Hermes 오프라인 시 Gemini API로 자동 폴백
        client = genai.Client(api_key=api_key)
        prompt = f"""다음 대화 내용을 바탕으로 100% 자연스러운 한국어로만 핵심 요약본을 작성하세요.
중요 지침:
- 일본어나 영어를 섞지 말고 오직 깔끔한 한국어로만 작성하세요.

Format:
SUMMARY: (대화의 핵심 주제 및 학습자의 언급 사항을 한국어로 2문장으로 요약)
FACTS: (상대방 학습자에 대해 알게 된 정보가 있다면 key=value 형식으로 작성, 없으면 NONE)

대화 내용:
{dialogue_text}"""

        res = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=300)
        )
        
        out = res.text or ""
        summary = ""
        for line in out.split("\n"):
            if line.startswith("SUMMARY:"):
                summary = line.replace("SUMMARY:", "").strip()
            elif line.startswith("FACTS:") and "NONE" not in line:
                fact_part = line.replace("FACTS:", "").strip()
                if "=" in fact_part:
                    k, v = fact_part.split("=", 1)
                    save_user_fact(k.strip(), v.strip())
                    
        if summary:
            save_session_summary(session_id, summary)
            print(f"[Gemini Summary] Updated summary for session '{session_id}': {summary[:40]}...")
    except Exception as e:
        print(f"[Long-Term Memory Error] {e}")


def _extract_grammar_errors_background(api_key: str, user_text: str, ai_text: str):
    """사용자 메시지와 AI 답장을 비교하여 문법 실수가 있다면 오답 노트 DB에 자동 적재 (Hermes 우선 -> Gemini 폴백)"""
    try:
        # 1. Hermes 로컬 에이전트 가용 시 우선 처리
        if is_hermes_available():
            err_data = extract_grammar_errors_with_hermes(user_text, ai_text)
            if err_data:
                orig, corr, expl = err_data
                save_user_memory("Grammar Error", orig, corr, expl)
                print(f"[Hermes Error Note] Automatically saved error note: '{orig}' -> '{corr}'")
            return

        # 2. Hermes 오프라인 시 Gemini API로 자동 폴백
        client = genai.Client(api_key=api_key)
        prompt = f"""다음 일본어 대화에서 사용자의 문법/어휘 실수를 AI가 교정해 준 경우 오답 노트 항목을 작성하세요.
실수가 없다면 NONE을 출력하세요.

Format (실수가 있을 때만):
ORIGINAL: (사용자가 실수한 틀린 문장)
CORRECTED: (올바른 정답 일본어 문장)
EXPLANATION: (한국어로 1문장 쉬운 문법 교정 설명)

사용자: {user_text}
AI 답장: {ai_text}"""

        res = client.models.generate_content(
            model="gemini-3.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=250)
        )
        
        out = res.text or ""
        if "NONE" in out or "ORIGINAL:" not in out:
            return

        orig, corr, expl = "", "", ""
        for line in out.split("\n"):
            if line.startswith("ORIGINAL:"):
                orig = line.replace("ORIGINAL:", "").strip()
            elif line.startswith("CORRECTED:"):
                corr = line.replace("CORRECTED:", "").strip()
            elif line.startswith("EXPLANATION:"):
                expl = line.replace("EXPLANATION:", "").strip()

        if orig and corr:
            save_user_memory("Grammar Error", orig, corr, expl)
            print(f"[Gemini Error Note] Automatically saved error note: '{orig}' -> '{corr}'")
    except Exception as e:
        print(f"[Error Note Memory Error] {e}")


def _analyze_feedback_background(api_key: str | None, message_id: str, session_id: str | None, rating: int, feedback_text: str | None = None):
    """부정적 피드백(-1) 발생 시 Hermes(우선) -> Gemini(폴백)로 유저가 싫어한 대답 패턴 분석 및 금지 지침 생성"""
    if rating != -1:
        return
        
    try:
        user_msg = "이전 질문"
        ai_msg = "이전 답장"
        if session_id:
            messages = get_session_messages(session_id)
            for i, m in enumerate(messages):
                if m["id"] == message_id:
                    ai_msg = m["content"]
                    if i > 0:
                        user_msg = messages[i-1]["content"]
                    break

        # 1. Hermes 우선 처리 (0원 연산)
        if is_hermes_available():
            rule = analyze_feedback_with_hermes(user_msg, ai_msg, rating, feedback_text)
            if rule:
                fact_key = f"disliked_pattern_{int(time.time())}"
                save_user_fact(fact_key, rule)
                print(f"[Hermes Feedback Refinement] Created rule: {rule}")
            return

        # 2. Gemini 폴백
        if api_key:
            client = genai.Client(api_key=api_key)
            prompt = f"""다음 대화에서 사용자가 AI 답장에 대해 👎(싫어요) 부정적 피드백을 남겼습니다.
이유/의견: {feedback_text or '어색하거나 비자연스러운 표현'}

사용자 질문: {user_msg}
AI 기존 답장: {ai_msg}

이 피드백을 바탕으로 향후 대화 시 금지하거나 개선해야 할 지침 규칙 1문장을 한국어로 작성하세요.
Format:
RULE: (향후 대화 시 피해야 할 구체적 규칙 1문장)"""

            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=200)
            )
            out = res.text or ""
            if "RULE:" in out:
                rule = out.replace("RULE:", "").strip()
                fact_key = f"disliked_pattern_{int(time.time())}"
                save_user_fact(fact_key, rule)
                print(f"[Gemini Feedback Refinement] Created rule: {rule}")
    except Exception as e:
        print(f"[Feedback Refinement Error] {e}")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/rag/status")
async def rag_status():
    """RAG 서버 토큰 설정 여부. 실제 retrieve 시 `rag_access.assert_rag_collection_access` 사용."""
    return {"rag_configured": rag_access_configured()}


@app.get("/api/mcp/prompts")
async def api_list_mcp_prompts():
    """사용 가능한 MCP Prompts 목록 반환"""
    return {"prompts": list_mcp_prompts()}


@app.post("/api/mcp/prompts/render")
async def api_render_mcp_prompt(req: MCPGetPromptRequest):
    """특정 MCP Prompt의 시스템 지시문 렌더링"""
    instruction = get_mcp_prompt_instruction(req.id, req.arguments)
    if not instruction:
        raise HTTPException(status_code=404, detail="요청한 MCP Prompt를 찾을 수 없습니다.")
    return {"id": req.id, "instruction": instruction}


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


@app.get("/api/facts")
async def api_list_facts():
    """학습자 장기 기억 프로필 (유저 팩트 및 세션 요약) 목록 반환"""
    facts = get_all_user_facts()
    sessions = get_all_sessions()
    summaries = []
    for s in sessions:
        sum_text = get_session_summary(s["session_id"])
        if sum_text:
            summaries.append({
                "session_id": s["session_id"],
                "title": s["title"],
                "summary": sum_text,
                "updated_at": s["updated_at"]
            })
    return {"facts": facts, "summaries": summaries}


@app.get("/api/trends")
async def api_list_trends():
    """OpenClaw가 수집한 일본 실시간 핫 트렌드 목록 반환"""
    trends = get_recent_live_trends(limit=10)
    return {"trends": trends}


@app.post("/api/trends/fetch")
async def api_fetch_trends(bg_tasks: BackgroundTasks):
    """OpenClaw 백그라운드 수집기 트리거"""
    bg_tasks.add_task(fetch_latest_japan_trends)
    return {"status": "fetching_scheduled"}


@app.post("/api/feedback")
async def api_submit_feedback(req: FeedbackRequest, bg_tasks: BackgroundTasks):
    """사용자 👍/👎 피드백 수신 및 백그라운드 Self-Refinement 분석"""
    fb = save_message_feedback(req.message_id, req.session_id, req.rating, req.feedback_text)
    if req.rating == -1:
        bg_tasks.add_task(_analyze_feedback_background, req.api_key, req.message_id, req.session_id, req.rating, req.feedback_text)
    return {"status": "saved", "feedback": fb}


@app.post("/api/chat")
@observe(name="gemini_chat")
async def chat(req: ChatRequest, bg_tasks: BackgroundTasks):
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
            req.roleplay_args,
            req.session_id
        )
        
        contents = []
        for item in req.history[-10:]:
            role = "user" if item.get("role") == "user" else "model"
            content = item.get("content", "")
            if content:
                contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
        
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=req.message)]))
        
        start_t = time.time()
        print(f"[Agentic Chat API START] Message: '{req.message}' | Autonomous Tool Calling Enabled")
        
        # Agentic Tool Calling Config (LLM이 질문 맥락을 자율 판단하여 구글 검색 툴 호출)
        config_agentic = types.GenerateContentConfig(
            system_instruction=sys_prompt,
            temperature=0.8,
            max_output_tokens=1000,
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        
        try:
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=contents,
                config=config_agentic
            )
        except Exception as tool_err:
            print(f"[Agentic Tool Calling Warning] ({tool_err}). Falling back to basic generation.")
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
        print(f"[Agentic Chat API END] Completed in {elapsed:.2f} seconds.")
        raw = response.text or ""
        clean_res = redact_sensitive_output(raw)
        
        # 세션 ID가 제공되었다면 유저 메시지 및 AI 답장 DB 저장
        if req.session_id:
            user_msg_id = f"usr_{int(time.time() * 1000)}"
            assistant_msg_id = f"ast_{int(time.time() * 1000) + 1}"
            save_message(user_msg_id, req.session_id, "user", req.message)
            save_message(assistant_msg_id, req.session_id, "assistant", clean_res)
            # 백그라운드 대화 요약 & 오답 노트 파싱 태스크 등록
            bg_tasks.add_task(_update_session_summary_background, req.api_key, req.session_id)
            bg_tasks.add_task(_extract_grammar_errors_background, req.api_key, req.message, clean_res)

        return {"response": clean_res}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/translate")
@observe(name="gemini_translate")
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
            max_output_tokens=1200
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
@observe(name="gemini_furigana")
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
            max_output_tokens=1200
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

# Translation Prompt (English System Instruction for Highest Precision)
TRANSLATE_PROMPT = """You are an expert Japanese-to-Korean translator.
Translate the provided Japanese text into natural, fluent, and polite Korean.
CRITICAL INSTRUCTIONS:
- Translate 100% of the input text from start to finish without omitting or truncating any sentences.
- Do NOT output any English explanations, notes, grammatical breakdown, or formatting markers (*, Sentence, etc.).
- Output ONLY the clean, final Korean translation text."""

# --------------------------------------------------------------------------------------

# Furigana Prompt (English System Instruction for Highest Precision)
FURIGANA_PROMPT = """You are a Japanese linguistics expert.
Add hiragana furigana readings in parentheses directly after every Kanji (漢字) in the provided Japanese text.
CRITICAL INSTRUCTIONS:
- Preserve 100% of the original Japanese text structure from start to finish without truncating or omitting any words.
- Add parentheses ONLY after Kanji (漢字). Do NOT add parentheses to Hiragana, Katakana, punctuation, or emojis.
- Do NOT include any English explanations, grammatical commentary, or notes.
- Output Format Example: 店内(てんない)でお召(め)し上(あ)がりですか、それともお持(も)ち帰(かえ)りですか？"""

# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
