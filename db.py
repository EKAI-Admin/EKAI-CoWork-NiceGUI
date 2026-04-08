import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "cowork.db"


def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS coworkers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            job_description TEXT NOT NULL,
            workflow TEXT NOT NULL,
            status TEXT DEFAULT 'active',
            model_provider TEXT DEFAULT 'claude',
            model_name TEXT DEFAULT 'claude-sonnet-4-20250514',
            join_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by INTEGER NOT NULL,
            FOREIGN KEY (created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            default_provider TEXT DEFAULT 'claude',
            default_model TEXT DEFAULT 'claude-sonnet-4-20250514',
            ollama_base_url TEXT DEFAULT 'http://localhost:11434',
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()


# --- User CRUD ---

def create_user(username: str, email: str, password_hash: str) -> int:
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
            (username, email, password_hash),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_user_by_username(username: str) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# --- CoWorker CRUD ---

def get_coworkers(user_id: int) -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM coworkers WHERE created_by = ? ORDER BY join_date DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_coworker(
    name: str,
    job_description: str,
    workflow: str,
    status: str,
    model_provider: str,
    model_name: str,
    created_by: int,
) -> int:
    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO coworkers
               (name, job_description, workflow, status, model_provider, model_name, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, job_description, workflow, status, model_provider, model_name, created_by),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_coworker(
    coworker_id: int,
    name: str,
    job_description: str,
    workflow: str,
    status: str,
    model_provider: str,
    model_name: str,
):
    conn = get_db()
    try:
        conn.execute(
            """UPDATE coworkers
               SET name=?, job_description=?, workflow=?, status=?, model_provider=?, model_name=?
               WHERE id=?""",
            (name, job_description, workflow, status, model_provider, model_name, coworker_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_coworker(coworker_id: int):
    conn = get_db()
    try:
        conn.execute("DELETE FROM coworkers WHERE id = ?", (coworker_id,))
        conn.commit()
    finally:
        conn.close()


# --- Settings CRUD ---

def get_settings(user_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM settings WHERE user_id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def upsert_settings(user_id: int, provider: str, model: str, ollama_url: str):
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO settings (user_id, default_provider, default_model, ollama_base_url)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET
                   default_provider=excluded.default_provider,
                   default_model=excluded.default_model,
                   ollama_base_url=excluded.ollama_base_url""",
            (user_id, provider, model, ollama_url),
        )
        conn.commit()
    finally:
        conn.close()
