"""
Hermes Agent Connector for NihongoChat.
Supports local Hermes models (via Ollama / vLLM / OpenAI-compatible API) or OpenRouter API.
Enables 0-cost, unlimited background memory summarization and grammar error analysis.
"""
import os
import requests
from typing import Optional, Dict, Any, Tuple

HERMES_API_BASE = os.getenv("HERMES_API_BASE", "http://localhost:11434/v1")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes3:latest")


def is_hermes_available() -> bool:
    """Check if local Hermes server (e.g., Ollama or vLLM) is online and reachable."""
    try:
        url = f"{HERMES_API_BASE.rstrip('/')}/models"
        res = requests.get(url, timeout=1.5)
        return res.status_code == 200
    except Exception:
        return False


def generate_with_hermes(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.2, max_tokens: int = 400) -> Optional[str]:
    """Generate completion using local Hermes LLM endpoint."""
    if not is_hermes_available():
        return None
        
    try:
        url = f"{HERMES_API_BASE.rstrip('/')}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": HERMES_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        res = requests.post(url, json=payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Hermes Connector Error] {e}")
        
    return None


def extract_grammar_errors_with_hermes(user_text: str, ai_text: str) -> Optional[Tuple[str, str, str]]:
    """Extract grammar error note using Hermes model."""
    prompt = f"""다음 일본어 대화에서 사용자의 문법/어휘 실수를 AI가 교정해 준 경우 오답 노트 항목을 작성하세요.
실수가 없다면 NONE을 출력하세요.

Format (실수가 있을 때만):
ORIGINAL: (사용자가 실수한 틀린 문장)
CORRECTED: (올바른 정답 일본어 문장)
EXPLANATION: (한국어로 1문장 쉬운 문법 교정 설명)

사용자: {user_text}
AI 답장: {ai_text}"""

    system_prompt = "You are a Japanese grammar expert assistant. Analyze dialogue errors accurately."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out or "NONE" in out or "ORIGINAL:" not in out:
        return None

    orig, corr, expl = "", "", ""
    for line in out.split("\n"):
        if line.startswith("ORIGINAL:"):
            orig = line.replace("ORIGINAL:", "").strip()
        elif line.startswith("CORRECTED:"):
            corr = line.replace("CORRECTED:", "").strip()
        elif line.startswith("EXPLANATION:"):
            expl = line.replace("EXPLANATION:", "").strip()

    if orig and corr:
        return (orig, corr, expl)
    return None


def summarize_session_with_hermes(dialogue_text: str) -> Tuple[Optional[str], Dict[str, str]]:
    """Summarize session dialogue and extract learner facts using Hermes model."""
    prompt = f"""다음 대話 내용을 바탕으로 100% 자연스러운 한국어로만 핵심 요약본을 작성하세요.
중요 지침:
- 일본어나 영어를 섞지 말고 오직 깔끔한 한국어로만 작성하세요.

Format:
SUMMARY: (대화의 핵심 주제 및 학습자의 언급 사항을 한국어로 2문장으로 요약)
FACTS: (상대방 학습자에 대해 알게 된 정보가 있다면 key=value 형식으로 작성, 없으면 NONE)

대화 내용:
{dialogue_text}"""

    system_prompt = "You are a helpful assistant providing concise Korean conversation summaries and learner facts."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.2)
    if not out:
        return None, {}

    summary = ""
    facts = {}
    for line in out.split("\n"):
        if line.startswith("SUMMARY:"):
            summary = line.replace("SUMMARY:", "").strip()
        elif line.startswith("FACTS:") and "NONE" not in line:
            fact_part = line.replace("FACTS:", "").strip()
            if "=" in fact_part:
                k, v = fact_part.split("=", 1)
                facts[k.strip()] = v.strip()

    return summary, facts


def analyze_feedback_with_hermes(user_text: str, ai_text: str, rating: int, feedback_text: Optional[str] = None) -> Optional[str]:
    """Analyze human dislike feedback (-1) using Hermes agent and extract refined prompt rule."""
    if rating != -1:
        return None
        
    prompt = f"""다음 대화에서 사용자가 AI 답장에 대해 👎(싫어요) 부정적 피드백을 남겼습니다.
이유/의견: {feedback_text or '어색하거나 비자연스러운 표현'}

사용자 질문: {user_text}
AI 기존 답장: {ai_text}

이 피드백을 바탕으로 향후 대화 시 금지하거나 개선해야 할 지침 규칙 1문장을 한국어로 작성하세요.
Format:
RULE: (향후 대화 시 피해야 할 구체적 규칙 1문장)"""

    system_prompt = "You are an AI refinement agent analyzing human feedback to improve Japanese dialogue response quality."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out or "RULE:" not in out:
        return None

    for line in out.split("\n"):
        if line.startswith("RULE:"):
            return line.replace("RULE:", "").strip()
            
    return None
