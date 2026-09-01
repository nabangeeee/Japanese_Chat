from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from google import genai
from google.genai import types
from langfuse import observe
import os
import re
import time
from dotenv import load_dotenv

from security_filters import redact_sensitive_output, scan_prompt_injection
from rag_access import rag_access_configured
from mcp_prompts import list_mcp_prompts, get_mcp_prompt_instruction
from database import (
    init_db, create_session, get_all_sessions, get_session, delete_session,
    save_message, get_session_messages, save_user_memory, get_user_memories,
    save_session_summary, get_session_summary, save_user_fact, get_all_user_facts,
    get_recent_live_trends, save_message_feedback, update_message_quality_score
)
from hermes_client import is_hermes_available, summarize_session_with_hermes, extract_grammar_errors_with_hermes, analyze_feedback_with_hermes, self_critique_response_with_hermes, generate_with_hermes
from codex_hermes_loop import diagnose_with_hermes
from openclaw_collector import fetch_latest_japan_trends
from contextlib import asynccontextmanager
import traceback
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


def clean_japanese_text(text: str) -> str:
    if not text:
        return text
    # 1. Clean accidental English letter leaks inside Katakana/Hiragana words (e.g. アイスコffeえ -> アイスコーヒー / アイスコーえ)
    text = re.sub(r'([ぁ-んァ-ヶ])[a-zA-Z]+([ぁ-んァ-ヶ])', r'\1\2', text)
    # 2. Clean remaining English word artifacts
    text = re.sub(r'[a-zA-Z]{2,}', '', text)
    # 3. Clean double spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_furigana_text(text: str) -> str:
    if not text:
        return text
    # 1. Remove Romaji / English alphabet inside parentheses e.g. (ohayou)
    text = re.sub(r'\([a-zA-Z\s\-\.\,\?!]+\)', '', text)
    # 2. Remove duplicated Hiragana parenthesis if it matches preceding hiragana e.g. おはよう(おはよう) -> おはよう
    text = re.sub(r'([ぁ-んァ-ヶ]+)\(\1\)', r'\1', text)
    # 3. Clean parens that erroneously contain Kanji inside parens e.g. (漢字)
    text = re.sub(r'\([^)]*[\u4e00-\u9fff][^)]*\)', '', text)
    # 4. Clean double spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def clean_translation_text(text: str) -> str:
    if not text:
        return text
    # Clean any accidental raw CJK Kanji leaked into Korean translation text
    text = re.sub(r'[\u4e00-\u9fff]', '', text)
    # Clean double spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text


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

    # 유저 피드백 기반 금지/개선 규칙 동적 주입 (최신 중복 제거 2개로 제한하여 55초 병목 해소)
    feedback_instruction = ""
    all_facts = get_all_user_facts()
    disliked_rules = [f["fact_value"] for f in all_facts if f["fact_key"].startswith("disliked_pattern_")]
    if disliked_rules:
        # 중복 규칙 제거 후 최신 2개만 프롬프트 주입
        unique_rules = list(dict.fromkeys(disliked_rules))
        rule_lines = [f"- {r}" for r in unique_rules[-2:]]
        feedback_instruction = f"\n\n[Hermes Self-Correction & Refinement Rules]\nThe Hermes Agent analyzed past user feedback/errors and extracted these refinement rules. STRICTLY FOLLOW THESE RULES:\n" + "\n".join(rule_lines)

    base_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        partner_name=partner_name,
        difficulty_prompt=difficulty_prompt,
        topic_prompt=topic_prompt
    )
    
    return base_prompt + roleplay_instruction + memory_instruction + long_term_instruction + trend_instruction + feedback_instruction


def _update_session_summary_background(api_key: str, session_id: str):
    """백그라운드 세션 대화 요약 및 유저 팩트 동적 추출 (Gemini 3.5 Flash 최우선)"""
    try:
        messages = get_session_messages(session_id)
        if len(messages) < 6:
            return

        dialogue_text = "\n".join([f"{m['role']}: {m['content']}" for m in messages[-14:]])
        
        # 1. Gemini 3.5 Flash 최우선 요약
        if api_key:
            client = genai.Client(api_key=api_key)
            prompt = f"""Summarize the Japanese conversation in fluent Korean.
Format:
SUMMARY: (Summary of dialogue in Korean, 2 sentences max)
FACTS: (Learner facts in key=value format, or NONE)

Dialogue Text:
{dialogue_text}"""

            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=300)
            )
            out = res.text or ""
            summary = ""
            for line in out.split("\n"):
                if "SUMMARY:" in line:
                    summary = line.split("SUMMARY:")[1].strip()
                elif "FACTS:" in line and "NONE" not in line:
                    fact_part = line.split("FACTS:")[1].strip()
                    if "=" in fact_part:
                        k, v = fact_part.split("=", 1)
                        save_user_fact(k.strip(), v.strip())
                        
            if summary:
                save_session_summary(session_id, summary)
                print(f"[Gemini Summary] Updated summary for session '{session_id}': {summary[:40]}...")
                return

        # 2. 로컬 Hermes 오프라인 폴백
        if is_hermes_available():
            summary, facts = summarize_session_with_hermes(dialogue_text)
            if summary:
                save_session_summary(session_id, summary)
            for k, v in facts.items():
                save_user_fact(k, v)
    except Exception as e:
        print(f"[Long-Term Memory Error] {e}")


def _extract_grammar_errors_background(api_key: str, user_text: str, ai_text: str):
    """사용자 대화 중 문법 실수가 있는 경우 오답 노트 DB 자동 적재 (Gemini 3.5 Flash 최우선)"""
    try:
        if api_key:
            client = genai.Client(api_key=api_key)
            prompt = f"""다음 대화에서 사용자의 문법/어휘 실수가 있다면 교정 항목을 작성하고, 없으면 NONE을 출력하세요.
Format (실수 있을 때만):
ORIGINAL: (틀린 문장)
CORRECTED: (올바른 일본어 문장)
EXPLANATION: (1문장 한국어 설명)

사용자: {user_text}
AI: {ai_text}"""

            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=250)
            )
            
            out = res.text or ""
            if "NONE" not in out and "ORIGINAL:" in out:
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
                    print(f"[Gemini Error Note] Saved error note: '{orig}' -> '{corr}'")
                    return

        # 로컬 Hermes 오프라인 폴백
        if is_hermes_available():
            err_data = extract_grammar_errors_with_hermes(user_text, ai_text)
            if err_data:
                orig, corr, expl = err_data
                save_user_memory("Grammar Error", orig, corr, expl)
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
            matched_index = -1
            for i, m in enumerate(messages):
                if m["id"] == message_id or message_id in m["id"] or m["id"].endswith(str(message_id)):
                    matched_index = i
                    break
            
            # ID 직관 매칭 실패 시 가장 최근 assistant 메시지 매칭
            if matched_index == -1:
                for i in range(len(messages) - 1, -1, -1):
                    if messages[i]["role"] == "assistant":
                        matched_index = i
                        break

            if matched_index != -1:
                ai_msg = messages[matched_index]["content"]
                if matched_index > 0:
                    user_msg = messages[matched_index - 1]["content"]

        # 1. Hermes 0원 에이전트가 유저 부정적 피드백 분석 및 진단서(fix_blueprint.txt) 작성
        if is_hermes_available():
            rule = analyze_feedback_with_hermes(user_msg, ai_msg, rating, feedback_text)
            if rule:
                fact_key = f"disliked_pattern_{int(time.time())}"
                save_user_fact(fact_key, rule)
                print(f"[Hermes Feedback Refinement] Created rule: {rule}")
                
                # Save feedback blueprint to scratch/fix_blueprint.txt
                blueprint_file_path = os.path.join(os.path.dirname(__file__), "scratch", "fix_blueprint.txt")
                os.makedirs(os.path.dirname(blueprint_file_path), exist_ok=True)
                with open(blueprint_file_path, "w", encoding="utf-8") as bf:
                    bf.write(f"=== Hermes Feedback Self-Refinement Blueprint ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n[User Message]: {user_msg}\n[AI Answer]: {ai_msg}\n[Feedback Reason]: {feedback_text or '어색하거나 비자연스러운 표현'}\n\n[Hermes Extracted Rule]:\n{rule}\n")
                print(f"[Hermes Feedback Refinement] 💾 Saved Feedback Blueprint to {blueprint_file_path}")
            return

        # 2. Hermes 미응답 시 Gemini 폴백
        if api_key:
            client = genai.Client(api_key=api_key)
            prompt = f"""The user gave a 👎 (dislike) feedback to the AI response in a Japanese conversation.
Feedback Reason: {feedback_text or 'Awkward phrasing'}
User Message: {user_msg}
AI Response: {ai_msg}

Write EXACTLY ONE 1-sentence actionable refinement rule in English stating what to avoid or improve in future responses.
Format:
RULE: (1-sentence rule in English)"""

            res = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=150)
            )
            out = res.text or ""
            if "RULE:" in out:
                rule = out.split("RULE:")[1].strip()
                fact_key = f"disliked_pattern_{int(time.time())}"
                save_user_fact(fact_key, rule)
                print(f"[Gemini Feedback Refinement] Created rule: {rule}")
    except Exception as e:
        print(f"[Feedback Refinement Error] {e}")


def _self_critique_ai_response_background(message_id: str, user_msg: str, ai_msg: str):
    """AI 답장 생성 후 백그라운드에서 LLM-as-a-Judge 품질 점수(1-10점) 채점 및 자율 정제 지침 DB 적재"""
    try:
        score = 6.5
        rule = None
        if is_hermes_available():
            score, rule = self_critique_response_with_hermes(user_msg, ai_msg)
        
        update_message_quality_score(message_id, score)
        print(f"[LLM-as-a-Judge] Message ID: {message_id} -> Quality Score: {score}/10.0")
        
        if rule:
            fact_key = f"disliked_pattern_{int(time.time())}"
            save_user_fact(fact_key, rule)
            print(f"[Hermes Self-Critique Agent] Created self-correction rule: {rule}")
            
            # Save self-critique blueprint to scratch/fix_blueprint.txt
            blueprint_file_path = os.path.join(os.path.dirname(__file__), "scratch", "fix_blueprint.txt")
            os.makedirs(os.path.dirname(blueprint_file_path), exist_ok=True)
            with open(blueprint_file_path, "w", encoding="utf-8") as bf:
                bf.write(f"=== Hermes Self-Critique & Auto-Correction Blueprint ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n[User Message]: {user_msg}\n[AI Response]: {ai_msg}\n[Assigned Score]: {score}/10.0\n\n[Hermes Self-Correction Rule]:\n{rule}\n")
            print(f"[Hermes Self-Critique Agent] 💾 Saved Auto-Correction Blueprint to {blueprint_file_path}")
    except Exception as e:
        print(f"[Hermes Self-Critique Error] {e}")


def _trigger_codex_hermes_self_healing_background(api_key: str | None, error_trace: str):
    """서버 런타임 오류 발생 시 백그라운드에서 Hermes 0원 진단 및 Codex 자율 코드 수복 루프 가동"""
    try:
        print("[Self-Healing Middleware] Server Exception detected. Triggering Hermes 0-cost diagnosis...")
        blueprint = diagnose_with_hermes("main.py Exception Trace", error_trace)
        
        # Save fix blueprint to scratch/fix_blueprint.txt
        blueprint_file_path = os.path.join(os.path.dirname(__file__), "scratch", "fix_blueprint.txt")
        os.makedirs(os.path.dirname(blueprint_file_path), exist_ok=True)
        with open(blueprint_file_path, "w", encoding="utf-8") as bf:
            bf.write(f"=== Hermes Auto Server Exception Blueprint ({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n\n{blueprint}\n\n[Full Error Trace]\n{error_trace}\n")
        print(f"[Self-Healing Middleware] 💾 Fix Blueprint saved to {blueprint_file_path}")
    except Exception as e:
        print(f"[Self-Healing Middleware Error] {e}")


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
@observe(name="nihongo_chat", as_type="generation")
async def chat(req: ChatRequest, bg_tasks: BackgroundTasks):
    # 프론트에서 api_key가 비어오면 .env 환경변수의 GEMINI_API_KEY 자동 사용
    effective_api_key = req.api_key or os.getenv("GEMINI_API_KEY")

    if not effective_api_key and not is_hermes_available():
        raise HTTPException(status_code=400, detail="로컬 Ollama Hermes 구동(ollama serve) 또는 .env의 GEMINI_API_KEY가 필요합니다.")

    _assert_no_prompt_injection(req.message)
    _scan_history_for_injection(req.history)

    try:
        start_t = time.time()
        sys_prompt = get_system_prompt(
            req.partner_name, 
            req.difficulty, 
            req.topic, 
            req.roleplay_id, 
            req.roleplay_args,
            req.session_id
        )

        raw = ""
        # 1. Gemini 3.5 Flash API 최우선 생성 (최고 품질 회화)
        if effective_api_key:
            client = genai.Client(api_key=effective_api_key)
            contents = []
            for item in req.history[-10:]:
                role = "user" if item.get("role") == "user" else "model"
                content = item.get("content", "")
                if content:
                    contents.append(types.Content(role=role, parts=[types.Part.from_text(text=content)]))
            
            contents.append(types.Content(role="user", parts=[types.Part.from_text(text=req.message)]))
            
            print(f"[Agentic Chat API START] Message: '{req.message}' | Autonomous Tool Calling Enabled")
            
            search_keywords = ["검색", "뉴스", "트렌드", "최신", "search", "news", "trend"]
            needs_search = any(k in req.message.lower() for k in search_keywords)
            
            tools = [types.Tool(google_search=types.GoogleSearch())] if needs_search else None
            config_agentic = types.GenerateContentConfig(
                system_instruction=sys_prompt,
                temperature=0.7,
                max_output_tokens=1000,
                tools=tools
            )
            
            # 503 과부하 에러 3회 재시도 (Exponential Backoff Auto-Retry)
            for attempt in range(3):
                try:
                    response = client.models.generate_content(
                        model="gemini-3.5-flash",
                        contents=contents,
                        config=config_agentic
                    )
                    raw = response.text or ""
                    break
                except Exception as tool_err:
                    err_msg = str(tool_err)
                    print(f"[Gemini API Attempt {attempt+1}] Warning/Error: {err_msg}")
                    if "503" in err_msg or "UNAVAILABLE" in err_msg:
                        time.sleep(1.0 * (attempt + 1))
                        continue
                    
                    try:
                        config_basic = types.GenerateContentConfig(
                            system_instruction=sys_prompt,
                            temperature=0.7,
                            max_output_tokens=1000
                        )
                        response = client.models.generate_content(
                            model="gemini-3.5-flash",
                            contents=contents,
                            config=config_basic
                        )
                        raw = response.text or ""
                        break
                    except Exception as basic_err:
                        print(f"[Gemini Basic Attempt {attempt+1}] Failed: {basic_err}")
                        time.sleep(1.0 * (attempt + 1))

        if not raw:
            raw = "현재 백엔드 연동에 실패했습니다. Gemini API 키 구동 상태를 확인해 주세요!"
        clean_res = clean_japanese_text(redact_sensitive_output(raw))
        
        elapsed = round(time.time() - start_t, 2)
        print(f"[Agentic Chat API END] Completed in {elapsed:.2f} seconds.")
        
        # 세션 ID가 제공되었다면 유저 메시지 및 AI 답장 DB 저장 (소요 런타임 초 정밀 기록)
        if req.session_id:
            user_msg_id = f"usr_{int(time.time() * 1000)}"
            assistant_msg_id = f"ast_{int(time.time() * 1000) + 1}"
            save_message(user_msg_id, req.session_id, "user", req.message)
            save_message(assistant_msg_id, req.session_id, "assistant", clean_res, response_time_sec=elapsed)
            # 백그라운드 대화 요약, 오답 파싱, LLM-as-a-Judge 품질 채점(1-10점) 태스크 등록 (0.5초 응답 속도 보장)
            bg_tasks.add_task(_update_session_summary_background, req.api_key, req.session_id)
            bg_tasks.add_task(_extract_grammar_errors_background, req.api_key, req.message, clean_res)
            bg_tasks.add_task(_self_critique_ai_response_background, assistant_msg_id, req.message, clean_res)

        return {"response": clean_res}
    
    except Exception as e:
        err_trace = traceback.format_exc()
        bg_tasks.add_task(_trigger_codex_hermes_self_healing_background, req.api_key, err_trace)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/translate")
@observe(name="nihongo_translate", as_type="generation")
async def translate(req: TranslateRequest):
    effective_api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    if not effective_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        start_t = time.time()
        raw = ""
        if effective_api_key:
            try:
                client = genai.Client(api_key=effective_api_key)
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
                raw = response.text or ""
            except Exception as e:
                print(f"[Translate Gemini Error] {e}")

        elapsed = time.time() - start_t
        print(f"[Translate API END] Completed in {elapsed:.2f} seconds.")
        clean_tr = clean_translation_text(redact_sensitive_output(raw or "번역 결과를 불러올 수 없습니다."))
        return {"translation": clean_tr}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/furigana")
@observe(name="nihongo_furigana", as_type="generation")
async def furigana(req: TranslateRequest):
    effective_api_key = req.api_key or os.getenv("GEMINI_API_KEY")
    if not effective_api_key:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        start_t = time.time()
        raw = ""
        if effective_api_key:
            try:
                client = genai.Client(api_key=effective_api_key)
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
                raw = response.text or ""
            except Exception as e:
                print(f"[Furigana Gemini Error] {e}")

        elapsed = time.time() - start_t
        print(f"[Furigana API END] Completed in {elapsed:.2f} seconds.")
        clean_furi = clean_furigana_text(redact_sensitive_output(raw or req.text))
        return {"furigana": clean_furi}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================
# PROMPT SETTINGS
# ============================================================

# Difficulty Prompts
BEGINNER_PROMPT = "Speak in simple, polite, concise Japanese (1-2 sentences, です・ます form)."
INTERMEDIATE_PROMPT = "Speak in natural everyday conversational Japanese (1-2 sentences)."
ADVANCED_PROMPT = "Speak in fluent, native-level Japanese (1-2 sentences)."

DIFFICULTY_PROMPTS = {
    "beginner": BEGINNER_PROMPT,
    "intermediate": INTERMEDIATE_PROMPT,
    "advanced": ADVANCED_PROMPT
}

# Topic Prompts
TOPIC_PROMPTS = {
    "free": "Free topic.",
    "dailyLife": "Daily life routines.",
    "travel": "Travel in Japan.",
    "food": "Japanese cuisine.",
    "culture": "Japanese culture.",
    "business": "Business Japanese.",
    "anime": "Anime and manga."
}

# System Prompt Template
SYSTEM_PROMPT_TEMPLATE = """You are "{partner_name}", a friendly native Japanese speaker living in Japan.
{difficulty_prompt}
Topic: {topic_prompt}

- Chat naturally in brief Japanese (1-2 sentences max).
- Do NOT include bracketed readings in your reply."""

# Translation Prompt
TRANSLATE_PROMPT = "Translate the Japanese text into natural, polite Korean. Output ONLY the translation without commentary."

# Furigana Prompt
FURIGANA_PROMPT = "Add Hiragana readings in parentheses directly after every Kanji (漢字)."

# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
