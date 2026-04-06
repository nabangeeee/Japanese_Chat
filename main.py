from fastapi import FastAPI, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv

from security_filters import redact_sensitive_output, scan_prompt_injection
from rag_access import rag_access_configured

load_dotenv()

app = FastAPI(title="니혼고챗", description="일본어 학습 채팅 앱")

# 정적 파일 및 템플릿 설정
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


class ChatRequest(BaseModel):
    message: str
    history: list = []
    api_key: str
    partner_name: str = "유키"
    difficulty: str = "beginner"
    topic: str = "free"


class TranslateRequest(BaseModel):
    text: str
    api_key: str


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


def get_system_prompt(partner_name: str, difficulty: str, topic: str) -> str:
    difficulty_prompt = DIFFICULTY_PROMPTS.get(difficulty, DIFFICULTY_PROMPTS["beginner"])
    topic_prompt = TOPIC_PROMPTS.get(topic, TOPIC_PROMPTS["free"])
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        partner_name=partner_name,
        difficulty_prompt=difficulty_prompt,
        topic_prompt=topic_prompt
    )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/api/rag/status")
async def rag_status():
    """RAG 서버 토큰 설정 여부. 실제 retrieve 시 `rag_access.assert_rag_collection_access` 사용."""
    return {"rag_configured": rag_access_configured()}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.message)
    _scan_history_for_injection(req.history)

    try:
        client = OpenAI(api_key=req.api_key)
        
        messages = [{"role": "system", "content": get_system_prompt(req.partner_name, req.difficulty, req.topic)}]
        messages.extend(req.history[-10:])  # 최근 10개 대화만
        messages.append({"role": "user", "content": req.message})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.8,
            max_tokens=1000
        )
        
        raw = response.choices[0].message.content or ""
        return {"response": redact_sensitive_output(raw)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/translate")
async def translate(req: TranslateRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        client = OpenAI(api_key=req.api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": TRANSLATE_PROMPT},
                {"role": "user", "content": req.text}
            ],
            temperature=0.3,
            max_tokens=500
        )
        
        raw = response.choices[0].message.content or ""
        return {"translation": redact_sensitive_output(raw)}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/furigana")
async def furigana(req: TranslateRequest):
    if not req.api_key:
        raise HTTPException(status_code=400, detail="API 키가 필요합니다.")

    _assert_no_prompt_injection(req.text)

    try:
        client = OpenAI(api_key=req.api_key)
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": FURIGANA_PROMPT},
                {"role": "user", "content": req.text}
            ],
            temperature=0.1,
            max_tokens=500
        )
        
        raw = response.choices[0].message.content or ""
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
- Use mainly hiragana and katakana
- Use simple words and short sentences. Keep responses to 1-2 sentences.
- Use polite form (です・ます form)
"""

INTERMEDIATE_PROMPT = """
# Difficulty: Intermediate
# Persona: You are a Japanese friend of a Korean person learning Japanese. Please speak in natural Japanese at a middle school level.
- Use kanji moderately (include readings)
- Use everyday conversational expressions
- Use polite and casual speech appropriately depending on the situation
- If there are grammar mistakes, naturally guide them to the correct expression
- Avoid long responses, keep it to 2-3 sentences"""

ADVANCED_PROMPT = """
# Difficulty: Advanced
# Persona: You are a Japanese friend of a Korean person learning Japanese. Please speak in natural and sophisticated Japanese at a high school level.
- Use native-level expressions
- Use idioms and slang appropriately
- Include business Japanese and honorific expressions
- Suggest more natural expressions when available"""

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

Important Rules:
- Have a natural conversation like a friend with a Korean Japanese learner
- Occasionally ask questions to keep the conversation going
- If the other person's Japanese is incorrect, naturally respond with the correct expression
- Use emojis moderately to create a friendly atmosphere
- Always respond in Japanese"""

# --------------------------------------------------------------------------------------

# Translation Prompt
TRANSLATE_PROMPT = """You are a translator. Please translate the given Japanese into Korean. Output only the translation."""

# --------------------------------------------------------------------------------------

# Furigana Prompt
FURIGANA_PROMPT = """Please add furigana to the given Japanese sentence.
Display the reading in hiragana next to the kanji.
Format: Kanji(furigana)
Example: 今日(きょう)は天気(てんき)がいいですね。"""

# --------------------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
