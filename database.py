"""
SQLite Database layer for NihongoChat.
Manages persistent conversation sessions, chat messages, and long-term learner memories (error notes).
"""
import sqlite3
import json
import os
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "nihongo_chat.db")


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback and close when used by the module's context managers."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def get_db_connection():
    import cloud_store
    if cloud_store.enabled():
        raise RuntimeError('Raw SQLite access is disabled in Supabase mode')
    conn = sqlite3.connect(DB_PATH, timeout=5.0, factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Initialize database tables if they do not exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL")
        
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
        
        cursor.execute("PRAGMA table_info(sessions)")
        if "roleplay_args" not in [row["name"] for row in cursor.fetchall()]:
            cursor.execute("ALTER TABLE sessions ADD COLUMN roleplay_args TEXT NOT NULL DEFAULT '{}'")

        # Messages table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                translation TEXT,
                furigana TEXT,
                response_time_sec REAL,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)
        
        # Auto-migration: check if response_time_sec and quality_score columns exist
        cursor.execute("PRAGMA table_info(messages)")
        cols = [row["name"] for row in cursor.fetchall()]
        if "response_time_sec" not in cols:
            cursor.execute("ALTER TABLE messages ADD COLUMN response_time_sec REAL")
        if "quality_score" not in cols:
            cursor.execute("ALTER TABLE messages ADD COLUMN quality_score REAL")
        
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

        cursor.execute("PRAGMA table_info(user_memories)")
        memory_columns = {row["name"] for row in cursor.fetchall()}
        if "next_review_at" not in memory_columns:
            cursor.execute("ALTER TABLE user_memories ADD COLUMN next_review_at TEXT")
        if "review_count" not in memory_columns:
            cursor.execute("ALTER TABLE user_memories ADD COLUMN review_count INTEGER NOT NULL DEFAULT 0")

        # Session Summaries table (Long-term Memory)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_summaries (
                session_id TEXT PRIMARY KEY,
                summary_text TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
            )
        """)

        # User Facts table (Learner Profile Fact Memory)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_key TEXT UNIQUE,
                fact_value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Human Feedback table (RLHF & Self-Refinement)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS message_feedbacks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL,
                session_id TEXT,
                rating INTEGER NOT NULL,
                feedback_text TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            DELETE FROM message_feedbacks
            WHERE id NOT IN (SELECT MAX(id) FROM message_feedbacks GROUP BY message_id)
        """)
        cursor.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS ux_message_feedbacks_message_id
            ON message_feedbacks(message_id)
        """)
        conn.commit()


# --- Session Operations ---

def create_session(session_id: str, title: str, partner_name: str, difficulty: str, topic: str, roleplay_id: Optional[str] = None, roleplay_args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    roleplay_args = roleplay_args if isinstance(roleplay_args, dict) else {}
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessions (session_id, title, partner_name, difficulty, topic, roleplay_id, created_at, updated_at, roleplay_args)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, title, partner_name, difficulty, topic, roleplay_id, now, now, json.dumps(roleplay_args, ensure_ascii=False))
        )
        conn.commit()
    return {
        "session_id": session_id,
        "title": title,
        "partner_name": partner_name,
        "difficulty": difficulty,
        "topic": topic,
        "roleplay_id": roleplay_id,
        "roleplay_args": roleplay_args,
        "created_at": now,
        "updated_at": now
    }


def _decode_session(row: sqlite3.Row) -> Dict[str, Any]:
    session = dict(row)
    try:
        args = json.loads(session.get("roleplay_args") or "{}")
    except (TypeError, ValueError):
        args = {}
    session["roleplay_args"] = args if isinstance(args, dict) else {}
    return session


def get_all_sessions() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        return [_decode_session(row) for row in rows]


def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        return _decode_session(row) if row else None


def delete_session(session_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """DELETE FROM message_feedbacks
               WHERE session_id = ? OR message_id IN (
                   SELECT id FROM messages WHERE session_id = ?
               )""",
            (session_id, session_id),
        )
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

def save_message(msg_id: str, session_id: str, role: str, content: str, translation: Optional[str] = None, furigana: Optional[str] = None, response_time_sec: Optional[float] = None, timestamp: Optional[str] = None) -> Dict[str, Any]:
    ts = timestamp or datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO messages (id, session_id, role, content, translation, furigana, response_time_sec, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (msg_id, session_id, role, content, translation, furigana, response_time_sec, ts)
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
        "response_time_sec": response_time_sec,
        "timestamp": ts
    }
def update_message_quality_score(msg_id: str, score: float):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE messages SET quality_score = ? WHERE id = ?", (score, msg_id))
        conn.commit()


def get_session_messages(session_id: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM messages WHERE session_id = ? ORDER BY timestamp ASC, rowid ASC", (session_id,))
        rows = cursor.fetchall()
        feedbacks = {row['message_id']: dict(row) for row in conn.execute(
            'SELECT message_id, rating, feedback_text FROM message_feedbacks WHERE session_id = ?',
            (session_id,),
        )}
        messages = [dict(row) for row in rows]
        for message in messages:
            feedback = feedbacks.get(message['id'])
            if feedback:
                message['feedback_rating'] = feedback['rating']
                message['feedback_text'] = feedback['feedback_text']
        return messages


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


# --- Long-Term Memory Summary & User Fact Operations ---

def save_session_summary(session_id: str, summary_text: str):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO session_summaries (session_id, summary_text, updated_at)
            VALUES (?, ?, ?)
            """,
            (session_id, summary_text, now)
        )
        conn.commit()


def get_session_summary(session_id: str) -> Optional[str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT summary_text FROM session_summaries WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        return row["summary_text"] if row else None


def save_user_fact(fact_key: str, fact_value: str):
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO user_facts (fact_key, fact_value, updated_at)
            VALUES (?, ?, ?)
            """,
            (fact_key, fact_value, now)
        )
        conn.commit()


def get_all_user_facts() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM user_facts ORDER BY updated_at DESC")
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


# --- Human Feedback Operations (RLHF & Self-Refinement) ---

def save_message_feedback(message_id: str, session_id: Optional[str], rating: int, feedback_text: Optional[str] = None) -> Dict[str, Any]:
    if rating not in {-1, 1}:
        raise ValueError("rating must be -1 or 1")
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # Serialize validation and the upsert with session deletion.
        cursor.execute("BEGIN IMMEDIATE")
        message = cursor.execute(
            "SELECT m.session_id, m.role FROM messages m JOIN sessions s ON s.session_id = m.session_id WHERE m.id = ?",
            (message_id,),
        ).fetchone()
        if message is None or message["role"] != "assistant":
            raise ValueError("feedback target must be an existing assistant message")
        if session_id is not None and session_id != message["session_id"]:
            raise ValueError("session_id does not match the feedback message")
        session_id = message["session_id"]
        cursor.execute(
            """
            INSERT INTO message_feedbacks (message_id, session_id, rating, feedback_text, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(message_id) DO UPDATE SET
                session_id = excluded.session_id,
                rating = excluded.rating,
                feedback_text = excluded.feedback_text,
                created_at = excluded.created_at
            """,
            (message_id, session_id, rating, feedback_text, now)
        )
        fb_id = cursor.execute(
            "SELECT id FROM message_feedbacks WHERE message_id = ?", (message_id,)
        ).fetchone()["id"]
        conn.commit()
    return {
        "id": fb_id,
        "message_id": message_id,
        "session_id": session_id,
        "rating": rating,
        "feedback_text": feedback_text,
        "created_at": now
    }


def get_negative_feedbacks(limit: int = 10) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM message_feedbacks WHERE rating = -1 ORDER BY created_at DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_message(message_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return dict(row) if row else None


def save_message_detail(message_id: str, field: str, value: str) -> bool:
    if field not in ("translation", "furigana"):
        raise ValueError("Unsupported message detail")
    with get_db_connection() as conn:
        return conn.execute(
            f"UPDATE messages SET {field} = ? WHERE id = ? AND role = 'assistant'",
            (value, message_id),
        ).rowcount == 1


def get_saved_turn(user_id: str, assistant_id: str, session_id: str, content: str):
    with get_db_connection() as conn:
        user = conn.execute("SELECT * FROM messages WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            return None
        if user["session_id"] != session_id or user["role"] != "user" or user["content"] != content:
            raise ValueError("Request ID already used for another message")
        assistant = conn.execute("SELECT * FROM messages WHERE id = ?", (assistant_id,)).fetchone()
        if assistant is None or assistant["session_id"] != session_id or assistant["role"] != "assistant":
            raise ValueError("Incomplete saved turn")
        return dict(assistant)


def save_chat_turn(user_id: str, assistant_id: str, session_id: str,
                   user_text: str, assistant_text: str, elapsed: float):
    """Save both sides atomically; concurrent retries reuse the committed turn."""
    now = datetime.now().isoformat()
    with get_db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = get_saved_turn(user_id, assistant_id, session_id, user_text)
        if existing:
            return existing["content"], False
        conn.executemany(
            "INSERT INTO messages (id, session_id, role, content, response_time_sec, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
            [(user_id, session_id, "user", user_text, None, now),
             (assistant_id, session_id, "assistant", assistant_text, elapsed, now)],
        )
        conn.execute("UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id))
    return assistant_text, True


def get_practice_memories(limit: int = 3) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM user_memories WHERE corrected_text IS NOT NULL AND corrected_text != '' "
            "AND (next_review_at IS NULL OR next_review_at <= ?) "
            "ORDER BY next_review_at ASC, created_at DESC, id DESC LIMIT ?",
            (datetime.now().isoformat(), limit),
        )]


def record_memory_review(memory_id: int, remembered: bool) -> bool:
    next_review = (datetime.now() + timedelta(days=7 if remembered else 1)).isoformat()
    with get_db_connection() as conn:
        return conn.execute(
            "UPDATE user_memories SET next_review_at = ?, review_count = review_count + 1 WHERE id = ?",
            (next_review, memory_id),
        ).rowcount == 1


# Keep the offline DB for migration and local maintenance. Cloud requests never
# fall back to it, including when authentication or the network fails.
def _backend_dispatch(local_function):
    from functools import wraps
    @wraps(local_function)
    def dispatch(*args, **kwargs):
        import cloud_store
        target = getattr(cloud_store, local_function.__name__) if cloud_store.enabled() else local_function
        return target(*args, **kwargs)
    return dispatch


for _operation in (
    'init_db', 'create_session', 'get_all_sessions', 'get_session', 'delete_session',
    'update_session_timestamp', 'save_message', 'update_message_quality_score',
    'get_session_messages', 'save_user_memory', 'get_user_memories', 'save_session_summary',
    'get_session_summary', 'save_user_fact', 'get_all_user_facts', 'save_message_feedback',
    'get_negative_feedbacks', 'get_message', 'save_message_detail', 'get_saved_turn',
    'save_chat_turn', 'get_practice_memories', 'record_memory_review',
):
    globals()[_operation] = _backend_dispatch(globals()[_operation])
