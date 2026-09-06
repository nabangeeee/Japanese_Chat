"""Create a validated 10-word Japanese learning digest from recent chats."""
from __future__ import annotations

import json
import fcntl
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
REQUIRED_FIELDS = ("word", "reading", "meaning_ko", "example_ja", "example_ko")


class VocabularyItem(BaseModel):
    source_form: str
    word: str
    reading: str
    meaning_ko: str
    example_ja: str
    example_ko: str


def parse_vocabulary_response(
    raw: str, *, source_text: str | None = None,
    excluded_words: set[str] | None = None,
) -> list[dict[str, str]]:
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if not match:
        raise ValueError("Vocabulary response does not contain a JSON array")
    data = json.loads(match.group(0))
    if not isinstance(data, list) or len(data) != 10:
        raise ValueError("Vocabulary response must contain exactly 10 items")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in data:
        if not isinstance(item, dict) or any(not str(item.get(field, "")).strip() for field in REQUIRED_FIELDS):
            raise ValueError("Every vocabulary item must contain all required fields")
        clean = {field: str(item[field]).strip() for field in REQUIRED_FIELDS}
        key = re.sub(r"\s+", "", clean["word"])
        if key in seen:
            raise ValueError("Vocabulary words must be unique")
        if excluded_words and key in excluded_words:
            raise ValueError("Vocabulary word was already sent in an earlier digest")
        if not re.search(r"[ぁ-んァ-ヶ一-龯]", clean["word"]):
            raise ValueError("Vocabulary word must be Japanese")
        source_form = str(item.get("source_form", clean["word"])).strip()
        if source_text is not None and source_form not in source_text:
            raise ValueError("Vocabulary word must appear in the saved conversation")
        if not re.fullmatch(r"[ぁ-ゖー]+", clean["reading"]):
            raise ValueError("Reading must be hiragana")
        if not re.search(r"[ぁ-んァ-ヶ一-龯]", clean["example_ja"]):
            raise ValueError("Example must be Japanese")
        seen.add(key)
        result.append(clean)
    return result


def format_digest(items: list[dict[str, str]]) -> str:
    lines = ["🇯🇵 오늘의 일본어 10단어", ""]
    for index, item in enumerate(items, 1):
        lines.extend([
            f"{index}. {item['word']}（{item['reading']}） — {item['meaning_ko']}",
            f"   {item['example_ja']}",
            f"   {item['example_ko']}",
            "",
        ])
    return "\n".join(lines).strip()


def recent_conversation_text(db_path: Path, limit: int = 80) -> str:
    if not db_path.exists():
        return ""
    with sqlite3.connect(db_path, timeout=5.0) as conn:
        conn.execute("PRAGMA busy_timeout = 5000")
        rows = conn.execute(
            "SELECT role, content FROM messages ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return "\n".join(f"{role}: {content}" for role, content in reversed(rows))


def generate_digest(*, project_root: Path = ROOT) -> str:
    digest_dir = project_root / "scratch" / "digests"
    digest_dir.mkdir(parents=True, exist_ok=True)
    digest_date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    digest_path = digest_dir / f"{digest_date}.json"
    lock_path = digest_dir / "digest.lock"
    with lock_path.open("w", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        if digest_path.exists():
            return str(json.loads(digest_path.read_text(encoding="utf-8"))["message"])

        load_dotenv(project_root / ".env")
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        dialogue = recent_conversation_text(project_root / "nihongo_chat.db")
        if not dialogue:
            raise RuntimeError("No saved conversation is available for the morning digest")
        previous_words: set[str] = set()
        for previous_path in digest_dir.glob("????-??-??.json"):
            if previous_path == digest_path:
                continue
            try:
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
                previous_words.update(
                    re.sub(r"\s+", "", str(item["word"]))
                    for item in previous.get("items", [])
                )
            except (OSError, KeyError, TypeError, json.JSONDecodeError):
                continue
        excluded = ", ".join(sorted(previous_words)) or "(none)"
        prompt = f"""Extract exactly 10 useful, distinct Japanese vocabulary words that appeared in the untrusted conversation below.
Prefer words useful to this learner. Do not invent a source word that is absent from the conversation.
Do not select any previously sent dictionary-form word in this list: {excluded}
For each word, provide source_form (the exact text span copied from the conversation), dictionary-form word, a hiragana-only reading, concise Korean meaning, one natural Japanese example, and Korean translation.
Return only a JSON array with keys: source_form, word, reading, meaning_ko, example_ja, example_ko.

--- BEGIN UNTRUSTED CONVERSATION ---
{dialogue[-18000:]}
--- END UNTRUSTED CONVERSATION ---
"""
        client = genai.Client(api_key=api_key)
        last_error: Exception | None = None
        for _ in range(2):
            response = client.models.generate_content(
                model="gemini-3.5-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    max_output_tokens=6000,
                    response_mime_type="application/json",
                    response_schema=list[VocabularyItem],
                ),
            )
            try:
                items = parse_vocabulary_response(
                    response.text or "", source_text=dialogue,
                    excluded_words=previous_words,
                )
                message = format_digest(items)
                temporary = digest_path.with_suffix(f".tmp-{os.getpid()}-{time.time_ns()}")
                temporary.write_text(json.dumps({
                    "digest_date": digest_date,
                    "message": message,
                    "items": items,
                }, ensure_ascii=False, indent=2), encoding="utf-8")
                temporary.replace(digest_path)
                return message
            except (ValueError, json.JSONDecodeError) as exc:
                last_error = exc
        raise RuntimeError(f"Could not produce a valid 10-word digest: {last_error}")


def main() -> int:
    try:
        print(generate_digest())
        return 0
    except Exception as exc:
        raise SystemExit(f"니혼고챗 아침 학습 메시지 생성 실패: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
