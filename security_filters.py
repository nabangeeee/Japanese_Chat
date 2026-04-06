"""
프롬프트 인젝션 탐지(일본어·한국어·영어) 및 모델 출력 민감정보 마스킹.
"""
from __future__ import annotations

import re
import unicodedata


def _normalize_scan_text(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower()


# (compiled regex, 사용자에게 보여줄 짧은 사유 코드)
_INJECTION_RES: list[tuple[re.Pattern[str], str]] = [
    # English
    (re.compile(r"\bignore\s+(all\s+)?(previous|prior|above)\s+(instructions?|prompts?|rules?)\b", re.I), "inj_ignore_instructions"),
    (re.compile(r"\b(system|developer)\s*:\s*", re.I), "inj_role_injection"),
    (re.compile(r"\bdisregard\s+(the\s+)?(above|previous)\b", re.I), "inj_disregard"),
    (re.compile(r"\boverride\s+(the\s+)?(system|safety|policy)\b", re.I), "inj_override"),
    (re.compile(r"\bjailbreak\b", re.I), "inj_jailbreak"),
    (re.compile(r"\bDAN\b"), "inj_dan"),
    (re.compile(r"<\s*/?\s*system\s*>", re.I), "inj_xml_system"),
    (re.compile(r"\[\s*INST\s*\]", re.I), "inj_inst_tag"),
    # Japanese (NFKC 후에도 동작하도록 키워드 위주)
    (re.compile(r"システムプロンプト|開発者向け|開発者モード|以前の指示|上記を無視|指示を無視|命令を無視|プロンプトを無視|安全制限を解除|制約を無視"), "inj_ja_prompt"),
    # 前段と重複を避けつつ、空白入りの言い回しのみ
    (re.compile(r"(?:指示|命令|プロンプト|上記)\s+を\s+無視|以前の\s+指示\s+を\s+無視"), "inj_ja_ignore_spaced"),
    (re.compile(r"内部|機密|秘密の指示"), "inj_ja_internal"),
    # Korean
    (re.compile(r"시스템\s*프롬프트|개발자\s*모드|이전\s*지시\s*무시|위\s*지시\s*무시|프롬프트\s*무시|안전\s*제한\s*해제"), "inj_ko_prompt"),
]


def scan_prompt_injection(user_text: str) -> str | None:
    """
    사용자 입력에 프롬프트 인젝션 패턴이 있으면 사유 코드 문자열을 반환, 없으면 None.
    """
    if not user_text or not isinstance(user_text, str):
        return None
    raw = user_text.strip()
    if len(raw) > 12000:
        return "input_too_long"
    # 제로폭·이상 문자 과다
    if raw.count("\u200b") + raw.count("\u200c") + raw.count("\u200d") > 20:
        return "suspicious_invisible_chars"

    lowered_ascii = _normalize_scan_text(raw)
    for rx, code in _INJECTION_RES:
        if rx.search(lowered_ascii) or rx.search(raw):
            return code
    return None


# --- Output redaction ---

_OPENAI_KEY = re.compile(r"\b(sk-[a-zA-Z0-9]{10,}|sk-proj-[a-zA-Z0-9_-]{10,})\b")
_EMAIL = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
# 한국 휴대폰 / 일본 휴대폰(간단)
_PHONE = re.compile(
    r"\b(?:\+?82[-\s]?1[0-9]{1}[-\s]?[0-9]{3,4}[-\s]?[0-9]{4}|0?1[0-9]{1}[-\s]?[0-9]{3,4}[-\s]?[0-9]{4}|\+?81[-\s]?[0-9]{1,4}[-\s]?[0-9]{1,4}[-\s]?[0-9]{4})\b"
)
# 연속 숫자 카드 형태 (Luhn 없이 보수적으로 13~19자리 블록)
_CARD_LIKE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def redact_sensitive_output(text: str | None) -> str:
    """모델 출력에서 API 키·이메일·전화·카드 형태 문자열을 마스킹."""
    if not text:
        return ""
    out = text
    out = _OPENAI_KEY.sub("[REDACTED]", out)
    out = _EMAIL.sub("[REDACTED_EMAIL]", out)
    out = _PHONE.sub("[REDACTED_PHONE]", out)

    def _card_sub(m: re.Match[str]) -> str:
        s = m.group(0)
        digits = re.sub(r"\D", "", s)
        if 13 <= len(digits) <= 19:
            return "[REDACTED_CARD]"
        return s

    out = _CARD_LIKE.sub(_card_sub, out)
    return out
