"""
RAG(또는 외부 지식 저장소) 접근 시 서버 측 권한 검사.

환경 변수:
  RAG_ACCESS_TOKEN   — 설정 시 Bearer 토큰과 일치해야 허용 (비어 있으면 RAG 호출은 거부).
  RAG_ALLOWED_COLLECTIONS — 쉼표 구분 컬렉션 ID. 비어 있으면 "*" 와 동일(토큰만 맞으면 허용).

새 RAG 엔드포인트를 만들 때 retrieve 전에 assert_rag_collection_access(...) 를 호출하세요.
"""
from __future__ import annotations

import os
from typing import Iterable


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    authorization = authorization.strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def _allowed_collections() -> set[str] | None:
    raw = os.getenv("RAG_ALLOWED_COLLECTIONS", "*").strip()
    if not raw or raw == "*":
        return None  # any collection ok (still need valid token if token is set)
    return {c.strip() for c in raw.split(",") if c.strip()}


def assert_rag_collection_access(
    collection_id: str,
    authorization_header: str | None,
) -> None:
    """
    토큰이 설정된 환경에서는 Bearer 토큰 필수 및 컬렉션 화이트리스트 검사.
    RAG_ACCESS_TOKEN 이 비어 있으면 RAG 사용 불가(503).
    """
    from fastapi import HTTPException

    secret = os.getenv("RAG_ACCESS_TOKEN", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="RAG is not enabled on this server (RAG_ACCESS_TOKEN not set).",
        )

    token = _parse_bearer(authorization_header)
    if not token or token != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing RAG credentials.")

    allowed = _allowed_collections()
    if allowed is not None and collection_id not in allowed:
        raise HTTPException(status_code=403, detail="This collection is not accessible.")


def rag_access_configured() -> bool:
    return bool(os.getenv("RAG_ACCESS_TOKEN", "").strip())


def collection_allowed(collection_id: str, allowed: Iterable[str] | None = None) -> bool:
    """테스트·내부용: 컬렉션 ID가 화이트리스트에 있는지."""
    s = _allowed_collections()
    if s is None:
        return True
    return collection_id in s
