import re
import shutil
import sqlite3
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "cowork.db"
COWORKERS_BASE = Path(__file__).parent / "coworkers"


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

def get_coworker_by_id(coworker_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM coworkers WHERE id = ?", (coworker_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


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
        create_coworker_folders(name)
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
        old = conn.execute("SELECT name FROM coworkers WHERE id = ?", (coworker_id,)).fetchone()
        conn.execute(
            """UPDATE coworkers
               SET name=?, job_description=?, workflow=?, status=?, model_provider=?, model_name=?
               WHERE id=?""",
            (name, job_description, workflow, status, model_provider, model_name, coworker_id),
        )
        conn.commit()
        if old and old["name"] != name:
            rename_coworker_folders(old["name"], name)
    finally:
        conn.close()


def delete_coworker(coworker_id: int):
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM coworkers WHERE id = ?", (coworker_id,)).fetchone()
        conn.execute("DELETE FROM coworkers WHERE id = ?", (coworker_id,))
        conn.commit()
        if row:
            delete_coworker_folders(row["name"])
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


# --- CoWorker Folder Management ---

def _sanitize_folder_name(name: str) -> str:
    return re.sub(r"[^\w\-]", "_", name.strip().lower())


def get_coworker_dir(name: str) -> Path:
    return COWORKERS_BASE / _sanitize_folder_name(name)


def create_coworker_folders(name: str) -> Path:
    base = get_coworker_dir(name)
    (base / "inputs").mkdir(parents=True, exist_ok=True)
    (base / "process").mkdir(parents=True, exist_ok=True)
    (base / "process" / "skills").mkdir(parents=True, exist_ok=True)
    (base / "outputs").mkdir(parents=True, exist_ok=True)
    (base / "runs").mkdir(parents=True, exist_ok=True)
    return base


def rename_coworker_folders(old_name: str, new_name: str):
    old_dir = get_coworker_dir(old_name)
    new_dir = get_coworker_dir(new_name)
    if old_dir.exists() and old_dir != new_dir:
        old_dir.rename(new_dir)
    elif not new_dir.exists():
        create_coworker_folders(new_name)


def delete_coworker_folders(name: str):
    d = get_coworker_dir(name)
    if d.exists():
        shutil.rmtree(d)


def get_prompt(name: str) -> str:
    prompt_file = get_coworker_dir(name) / "process" / "prompt.md"
    if prompt_file.exists():
        return prompt_file.read_text()
    return ""


def save_prompt(name: str, prompt: str):
    prompt_file = get_coworker_dir(name) / "process" / "prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt)


# --- Skill Bundle Management ---

def get_skills_dir(name: str) -> Path:
    d = get_coworker_dir(name) / "process" / "skills"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_skills(name: str) -> list[str]:
    """Return sorted list of skill folder names under process/skills/."""
    d = get_skills_dir(name)
    return sorted(f.name for f in d.iterdir() if f.is_dir())


def save_skill_bundle(coworker_name: str, filename: str, content: bytes):
    """Extract a .zip or .skill file into process/skills/<skill-name>/.

    The skill name is derived from the filename (without extension).
    """
    stem = Path(filename).stem
    skill_dir = get_skills_dir(coworker_name) / _sanitize_folder_name(stem)
    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    skill_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(BytesIO(content)) as zf:
            zf.extractall(skill_dir)
    except zipfile.BadZipFile:
        # Not a zip — treat as a single text skill file
        (skill_dir / filename).write_bytes(content)


def delete_skill(coworker_name: str, skill_name: str):
    """Remove an entire skill folder."""
    path = get_skills_dir(coworker_name) / skill_name
    if path.exists() and path.is_dir():
        shutil.rmtree(path)


def get_skill_files(coworker_name: str, skill_name: str) -> list[str]:
    """List files inside a skill folder."""
    d = get_skills_dir(coworker_name) / skill_name
    if not d.exists():
        return []
    return sorted(str(f.relative_to(d)) for f in d.rglob("*") if f.is_file())


# --- Run Management ---

def start_run(name: str) -> tuple[Path, list[str]]:
    """Create a timestamped run folder, copy inputs and prompt into it.

    Returns (run_dir, list of copied input filenames).
    Raises ValueError if no prompt or no input files exist.
    """
    cw_dir = get_coworker_dir(name)
    inputs_dir = cw_dir / "inputs"
    prompt_file = cw_dir / "process" / "prompt.md"

    if not prompt_file.exists() or not prompt_file.read_text().strip():
        raise ValueError("No prompt configured. Set a prompt first.")

    input_files = [f for f in inputs_dir.iterdir() if f.is_file()] if inputs_dir.exists() else []
    if not input_files:
        raise ValueError("No input files found in the inputs/ folder.")

    # Create timestamped run directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = cw_dir / "runs" / timestamp
    (run_dir / "inputs").mkdir(parents=True, exist_ok=True)
    (run_dir / "process").mkdir(parents=True, exist_ok=True)
    (run_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Copy input files
    copied = []
    for f in input_files:
        shutil.copy2(f, run_dir / "inputs" / f.name)
        copied.append(f.name)

    # Copy prompt
    shutil.copy2(prompt_file, run_dir / "process" / "prompt.md")

    # Copy skill bundle folders
    skills_dir = cw_dir / "process" / "skills"
    if skills_dir.exists() and any(skills_dir.iterdir()):
        shutil.copytree(skills_dir, run_dir / "process" / "skills", dirs_exist_ok=True)

    return run_dir, copied


def get_runs(name: str) -> list[dict]:
    """Return list of runs for a coworker, newest first."""
    runs_dir = get_coworker_dir(name) / "runs"
    if not runs_dir.exists():
        return []
    runs = []
    for d in sorted(runs_dir.iterdir(), reverse=True):
        if d.is_dir():
            input_count = len(list((d / "inputs").iterdir())) if (d / "inputs").exists() else 0
            output_count = len(list((d / "outputs").iterdir())) if (d / "outputs").exists() else 0
            runs.append({
                "timestamp": d.name,
                "path": str(d),
                "input_count": input_count,
                "output_count": output_count,
            })
    return runs
