"""
SQLite Database layer for NihongoChat.
Manages persistent conversation sessions, chat messages, and long-term learner memories (error notes).
"""
import sqlite3
import os
from typing import List, Dict, Any, Optional
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nihongo_chat.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database tables if they do not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                partner_name TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                topic TEXT NOT NULL,
                roleplay_id TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                translation TEXT,
                furigana TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        # User memories & error notes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                original_text TEXT,
                corrected_text TEXT,
                explanation TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# --- Session Operations ---

def create_session(session_id: str, title: str, partner_name: str, difficulty: str, topic: str, roleplay_id: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (session_id, title, partner_name, difficulty, topic, roleplay_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, title, partner_name, difficulty, topic, roleplay_id, now, now)
        )
        conn.commit()
    return {
        "session_id": session_id,
        "title": title,
        "partner_name": partner_name,
        "difficulty": difficulty,
        "topic": topic,
        "roleplay_id": roleplay_id,
        "created_at": now,
        "updated_at": now
    }


def get_all_sessions() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_session(session_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        conn.commit()
        return cursor.rowcount > 0


def update_session_timestamp(session_id: str):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
        conn.commit()


# --- Message Operations ---

def save_message(msg_id: str, session_id: str, role: str, content: str, translation: Optional[str] = None, furigana: Optional[str] = None, timestamp: Optional[str] = None) -> Dict[str, Any]:
    ts = timestamp or datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO messages (id, session_id, role, content, translation, furigana, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, role, content, translation, furigana, ts)
        )
        conn.commit()
    update_session_timestamp(session_id)
    return {
        "id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "translation": translation,
        "furigana": furigana,
        "timestamp": ts
    }


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC", (session_id,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# --- Learner Memory & Error Note Operations ---

def save_user_memory(category: str, original_text: str, corrected_text: str, explanation: str) -> Dict[str, Any]:
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO user_memories (category, original_text, corrected_text, explanation, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (category, original_text, corrected_text, explanation, now)
        )
        conn.commit()
        memory_id = cursor.lastrowid
    return {
        "id": memory_id,
        "category": category,
        "original_text": original_text,
        "corrected_text": corrected_text,
        "explanation": explanation,
        "created_at": now
    }


def get_user_memories(limit: int = 20) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_memories ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
