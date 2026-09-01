"""
Hermes Agent Connector for NihongoChat.
Supports local Hermes models (via Ollama / vLLM / OpenAI-compatible API) or OpenRouter API.
Enables 0-cost, unlimited background memory summarization and grammar error analysis.
"""
import os
import requests
from typing import Optional, Dict, Any, Tuple

HERMES_API_BASE = os.getenv("HERMES_API_BASE", "http://localhost:11434/v1")
HERMES_MODEL = os.getenv("HERMES_MODEL", "hermes3:3b")


def is_hermes_available() -> bool:
    """Check if local Ollama LLM server is online and reachable."""
    try:
        url = f"{HERMES_API_BASE.rstrip('/')}/models"
        res = requests.get(url, timeout=1.5)
        return res.status_code == 200
    except Exception:
        return False


def generate_with_hermes(prompt: str, system_prompt: Optional[str] = None, temperature: float = 0.2, max_tokens: int = 300, model_override: Optional[str] = None) -> Optional[str]:
    """Generate completion using local LLM endpoint (Hermes 3 for offline fallback & code diagnosis) with lightweight memory management."""
    if not is_hermes_available():
        return None
        
    try:
        url = f"{HERMES_API_BASE.rstrip('/')}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        payload = {
            "model": model_override or HERMES_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "keep_alive": "3m"  # 3분 후 메모리 자동 해제하여 맥북 렉 방지
        }
        
        res = requests.post(url, json=payload, timeout=20)
        if res.status_code == 200:
            data = res.json()
            return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print(f"[Hermes Connector Error] {e}")
        
    return None


def extract_grammar_errors_with_hermes(user_text: str, ai_text: str) -> Optional[Tuple[str, str, str]]:
    """Extract grammar error note using Hermes model with 100% English prompt."""
    prompt = f"""Analyze the Japanese dialogue below. If the user made a grammar/vocabulary mistake and the AI corrected it, extract a grammar error item.
If there is no user error, output ONLY: NONE

Format (ONLY if error exists):
ORIGINAL: (User's incorrect Japanese sentence)
CORRECTED: (Corrected Japanese sentence)
EXPLANATION: (1-sentence easy grammar explanation in Korean)

User: {user_text}
AI Response: {ai_text}"""

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
    """Summarize session dialogue and extract learner facts using Hermes model with 100% English prompt."""
    prompt = f"""Summarize the following Japanese conversation into natural Korean.
CRITICAL INSTRUCTIONS:
- Translate ALL Japanese words into natural Korean in the summary text. Absolutely NO Japanese characters (Hiragana, Katakana, Kanji) allowed!
- Output ONLY in the exact format below.

Format:
SUMMARY: (Summary of dialogue in natural Korean, 2 sentences max)
FACTS: (Learner facts in key=value format, or NONE)

Dialogue Text:
{dialogue_text}"""

    system_prompt = "You are a professional Korean summarization agent. Write clean Korean summaries without Japanese words."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out:
        return None, {}

    summary = ""
    facts = {}
    for line in out.split("\n"):
        if "SUMMARY:" in line:
            summary = line.split("SUMMARY:")[1].strip()
        elif "FACTS:" in line and "NONE" not in line:
            fact_part = line.split("FACTS:")[1].strip()
            if "=" in fact_part:
                k, v = fact_part.split("=", 1)
                facts[k.strip()] = v.strip()

    # Clean FACTS leftover from summary if present
    if "FACTS:" in summary:
        summary = summary.split("FACTS:")[0].strip()

    return summary, facts


def analyze_feedback_with_hermes(user_text: str, ai_text: str, rating: int, feedback_text: Optional[str] = None) -> Optional[str]:
    """Analyze human dislike feedback (-1) using Hermes agent with 100% English rule output."""
    if rating != -1:
        return None
        
    prompt = f"""The user gave a 👎 (dislike) feedback to the AI response in a Japanese conversation.
Feedback Reason: {feedback_text or 'Awkward or unnatural phrasing'}

User Message: {user_text}
AI Response: {ai_text}

Based on this feedback, write EXACTLY ONE 1-sentence actionable refinement rule in English stating what to avoid or improve in future responses.
Format:
RULE: (1-sentence concise rule in English)"""

    system_prompt = "You are an AI refinement agent analyzing human feedback to improve Japanese dialogue response quality."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out or "RULE:" not in out:
        return None

    for line in out.split("\n"):
        if "RULE:" in line:
            return line.split("RULE:")[1].strip()
            
    return None


def self_critique_response_with_hermes(user_text: str, ai_text: str) -> Tuple[float, Optional[str]]:
    """Act as LLM-as-a-Judge to grade Japanese response on compressed 1-10 scale and extract refinement rules."""
    prompt = f"""You are a Japanese Dialogue Quality Auditor (LLM-as-a-Judge).
Evaluate the AI response in a Japanese conversation/roleplay setting.

[User Input]: {user_text}
[AI Response]: {ai_text}

AUDIT CRITERIA:
1. Persona & Role Fidelity (Maintains assigned role/friend persona without role confusion)
2. Japanese Phrasing & Naturalness (Fluent native grammar & vocabulary)
3. Conciseness (1-2 sentences max)

OUTPUT FORMAT:
SCORE: (Float from 1.0 to 10.0)
RULE: (Brief 1-sentence English refinement rule if flawed, else NONE)

Audit Result:"""

    system_prompt = "You are a Japanese dialogue quality auditor."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out:
        return 5.5, None

    score = 5.5
    rule = None
    for line in out.split("\n"):
        if "SCORE:" in line:
            try:
                score_val = float(line.split("SCORE:")[1].strip().split()[0])
                # Compress score toward center of scale (1-10 scale -> 3.0 to 7.0 range)
                score = round(3.0 + (score_val / 10.0) * 4.0, 1)
            except Exception:
                pass
        elif "RULE:" in line and "NONE" not in line:
            clean_rule = line.split("RULE:")[1].strip().strip('"').strip("'").strip("`")
            if clean_rule:
                rule = clean_rule

    return score, rule


def orchestrate_speaker_turn_with_hermes(user_text: str, dialogue_history: list = None) -> str:
    """Hermes 0-cost Orchestrator decides multi-speaker turn routing in a 3-party roleplay setting."""
    prompt = f"""You are a Multi-Agent Turn Orchestrator for a Japanese Cafe 3-Party Roleplay.
The scene includes: User (Customer), Staff (Yuki, Cafe Barista), and Regular (Ken, Local Customer).

[User Input]: {user_text}

Decide which AI speakers should respond in this turn.
Rules:
- If User asks for order/bill/menu directly to staff -> STAFF_ONLY
- If User greets generally or asks for recommendations -> STAFF_AND_REGULAR
- If User talks to the regular customer -> REGULAR_ONLY

Output EXACTLY ONE string: STAFF_ONLY, REGULAR_ONLY, or STAFF_AND_REGULAR."""

    system_prompt = "You are a Multi-Agent Turn Orchestrator routing dialogue speaker turns."
    out = generate_with_hermes(prompt, system_prompt=system_prompt, temperature=0.1)
    if not out:
        return "STAFF_AND_REGULAR"
    
    clean_out = out.upper().strip()
    if "REGULAR_ONLY" in clean_out:
        return "REGULAR_ONLY"
    elif "STAFF_ONLY" in clean_out:
        return "STAFF_ONLY"
    else:
        return "STAFF_AND_REGULAR"
