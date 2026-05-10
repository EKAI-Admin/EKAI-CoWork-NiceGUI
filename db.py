import json as _json
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

        CREATE TABLE IF NOT EXISTS runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coworker_id INTEGER NOT NULL,
            coworker_name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            model_provider TEXT NOT NULL DEFAULT 'claude',
            model_name TEXT NOT NULL DEFAULT '',
            workflow TEXT DEFAULT '',
            run_dir TEXT DEFAULT '',
            status TEXT DEFAULT 'pending',
            progress_message TEXT DEFAULT '',
            files_total INTEGER DEFAULT 0,
            files_processed INTEGER DEFAULT 0,
            has_report INTEGER DEFAULT 0,
            pdf_files TEXT DEFAULT '[]',
            error TEXT DEFAULT '',
            script_log TEXT DEFAULT '',
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            FOREIGN KEY (coworker_id) REFERENCES coworkers(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)
    # Migrate existing databases: add script_log column if missing
    try:
        conn.execute("SELECT script_log FROM runs LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE runs ADD COLUMN script_log TEXT DEFAULT ''")

    # CoWorker feedback log (Reward / Penalise / Suspend)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS coworker_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            coworker_id INTEGER NOT NULL,
            coworker_name TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            feedback_type TEXT NOT NULL,
            content TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (coworker_id) REFERENCES coworkers(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """)

    # Departments table (DB-backed metadata for workflows/departments)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            icon TEXT NOT NULL DEFAULT 'work',
            color TEXT NOT NULL DEFAULT 'blue',
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Seed default departments on first run
    cur = conn.execute("SELECT COUNT(*) FROM departments")
    if cur.fetchone()[0] == 0:
        default_depts = [
            ("Code Review",            "code",              "blue",    ""),
            ("Documentation",          "menu_book",         "teal",    ""),
            ("Testing",                "science",           "purple",  ""),
            ("Deployment",             "rocket_launch",     "orange",  ""),
            ("Data Analysis",          "analytics",         "indigo",  ""),
            ("Customer Support",       "support_agent",     "green",   ""),
            ("Content Creation",       "draw",              "pink",    ""),
            ("Security Audit",         "security",          "red",     ""),
            ("Performance Monitoring", "speed",             "cyan",    ""),
            ("Bug Triage",             "bug_report",        "amber",   ""),
        ]
        conn.executemany(
            "INSERT INTO departments (name, icon, color, description) VALUES (?, ?, ?, ?)",
            default_depts,
        )

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


class SkillValidationError(Exception):
    """Raised when an uploaded skill bundle fails validation."""


def validate_skill_bundle(skill_dir: Path) -> list[str]:
    """Validate an extracted skill bundle and return a list of warnings/errors.

    Checks:
    1. skill.json is valid JSON with correct structure (if present)
    2. Pipeline scripts referenced in skill.json actually exist
    3. Extraction rules file exists (if declared)
    4. SKILL.md has valid frontmatter (if present, no skill.json)

    Returns an empty list if everything is valid.
    Raises SkillValidationError for critical issues that should block the upload.
    """
    errors: list[str] = []

    # Search for skill.json (handle double-nested zips)
    manifest_path = None
    manifest = None
    for candidate in [skill_dir, *(c for c in skill_dir.iterdir() if c.is_dir())]:
        p = candidate / "skill.json"
        if p.exists():
            manifest_path = p
            break

    if manifest_path:
        # --- Validate skill.json ---
        try:
            raw = manifest_path.read_text()
            manifest = _json.loads(raw)
        except _json.JSONDecodeError as e:
            raise SkillValidationError(f"skill.json has invalid JSON: {e}")
        except OSError as e:
            raise SkillValidationError(f"Cannot read skill.json: {e}")

        if not isinstance(manifest, dict):
            raise SkillValidationError("skill.json must be a JSON object, got " + type(manifest).__name__)

        # Check required fields
        if "name" not in manifest:
            errors.append("skill.json: missing 'name' field")

        # Validate pipeline
        pipeline = manifest.get("pipeline")
        if pipeline is not None:
            if not isinstance(pipeline, list):
                raise SkillValidationError("skill.json: 'pipeline' must be a list")
            skill_root = manifest_path.parent
            for i, step in enumerate(pipeline):
                if not isinstance(step, dict):
                    errors.append(f"Pipeline step {i}: must be an object")
                    continue
                step_name = step.get("step", f"step_{i}")
                script_rel = step.get("script", "")
                if not script_rel:
                    errors.append(f"Pipeline step '{step_name}': missing 'script' field")
                else:
                    script_path = skill_root / script_rel
                    if not script_path.exists():
                        raise SkillValidationError(
                            f"Pipeline step '{step_name}': script not found: {script_rel}"
                        )
                    if not script_path.is_file():
                        errors.append(f"Pipeline step '{step_name}': '{script_rel}' is not a file")

        # Validate extraction rules reference
        extraction = manifest.get("extraction")
        if extraction and isinstance(extraction, dict):
            rules_rel = extraction.get("rules", "")
            if rules_rel:
                rules_path = manifest_path.parent / rules_rel
                if not rules_path.exists():
                    raise SkillValidationError(
                        f"Extraction rules file not found: {rules_rel}"
                    )
                # Validate rules file is valid JSON
                try:
                    _json.loads(rules_path.read_text())
                except _json.JSONDecodeError as e:
                    raise SkillValidationError(f"Extraction rules file has invalid JSON: {e}")
    else:
        # No skill.json — check for SKILL.md fallback
        skill_md = None
        for candidate in [skill_dir, *(c for c in skill_dir.iterdir() if c.is_dir())]:
            p = candidate / "SKILL.md"
            if p.exists():
                skill_md = p
                break
        if skill_md is None:
            errors.append("No skill.json or SKILL.md found — bundle may not work as expected")

    return errors


def save_skill_bundle(coworker_name: str, filename: str, content: bytes) -> list[str]:
    """Extract a .zip or .skill file into process/skills/<skill-name>/.

    The skill name is derived from the filename (without extension).
    Returns a list of validation warnings (empty if clean).
    Raises SkillValidationError if the bundle has critical issues.
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

    # Validate the extracted bundle
    try:
        warnings = validate_skill_bundle(skill_dir)
    except SkillValidationError:
        # Critical error — remove the extracted files and re-raise
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise

    return warnings


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


def _parse_skill_md_frontmatter(md_path: Path) -> dict:
    """Parse YAML-ish frontmatter from a SKILL.md file.

    Supports simple `key: value` pairs and folded scalars (`>`). Returns an
    empty dict if no frontmatter is present.
    """
    try:
        text = md_path.read_text()
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    block = text[3:end].strip("\n")
    result: dict = {}
    current_key: str | None = None
    folded_lines: list[str] = []
    for raw in block.splitlines():
        # Continuation of a folded scalar (indented line after `key: >`)
        if current_key is not None and (raw.startswith(" ") or raw.startswith("\t")):
            folded_lines.append(raw.strip())
            continue
        if current_key is not None:
            result[current_key] = " ".join(folded_lines).strip()
            current_key, folded_lines = None, []
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        key = key.strip()
        value = value.strip()
        if value == ">" or value == "|":
            current_key = key
            folded_lines = []
        else:
            result[key] = value.strip('"').strip("'")
    if current_key is not None:
        result[current_key] = " ".join(folded_lines).strip()
    return result


def load_coworker_skill_manifest(coworker_name: str) -> dict | None:
    """Load a skill manifest from a coworker's process/skills/ folder.

    Prefers `skill.json` (with a `pipeline` list). Falls back to parsing the
    YAML frontmatter of `SKILL.md` for AI-only skills that have no scripted
    pipeline. Handles double-nested zip extraction
    (`skill_name/skill_name/...`). Returns the parsed manifest dict with
    `_skill_dir` pointing to the skill root, or None if nothing is found.
    """
    import json
    skills_dir = get_skills_dir(coworker_name)
    if not skills_dir.exists():
        return None

    md_fallback: dict | None = None
    for skill_folder in sorted(skills_dir.iterdir()):
        if not skill_folder.is_dir():
            continue
        for candidate in [skill_folder, *sorted(
            c for c in skill_folder.iterdir() if c.is_dir()
        )]:
            manifest_path = candidate / "skill.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    if "pipeline" in manifest and isinstance(manifest["pipeline"], list):
                        manifest["_skill_dir"] = candidate
                        return manifest
                except (json.JSONDecodeError, OSError):
                    continue
            # Remember the first SKILL.md found as a fallback
            if md_fallback is None:
                md_path = candidate / "SKILL.md"
                if md_path.exists():
                    front = _parse_skill_md_frontmatter(md_path)
                    # Check for Claude skill format: SKILL.md + scripts/ folder
                    scripts_dir = candidate / "scripts"
                    claude_pipeline: list = []
                    if scripts_dir.is_dir():
                        # Synthesize pipeline (same logic as ai_runner, but display-only)
                        from ai_runner import _synthesize_claude_manifest
                        # Use placeholder paths for display; actual paths resolved at runtime
                        synth = _synthesize_claude_manifest(
                            candidate,
                            outputs_dir=Path("{outputs}"),
                            inputs_dir=Path("{inputs}"),
                        )
                        if synth:
                            claude_pipeline = synth.get("pipeline", [])
                    md_fallback = {
                        "name": front.get("name", candidate.name),
                        "description": front.get("description", ""),
                        "pipeline": claude_pipeline,
                        "_skill_dir": candidate,
                        "_source": "claude-skill" if claude_pipeline else "SKILL.md",
                    }
    return md_fallback


# --- Run Management (filesystem) ---

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


# --- Run DB CRUD ---

def create_run_record(
    coworker_id: int,
    coworker_name: str,
    user_id: int,
    model_provider: str = "claude",
    model_name: str = "",
    workflow: str = "",
) -> int:
    """Insert a new run record and return its id."""
    conn = get_db()
    try:
        cursor = conn.execute(
            """INSERT INTO runs
               (coworker_id, coworker_name, user_id, model_provider, model_name, workflow, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (coworker_id, coworker_name, user_id, model_provider, model_name, workflow),
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def update_run_progress(run_id: int, message: str, **kwargs):
    """Update progress message and optional numeric fields for a run."""
    conn = get_db()
    try:
        sets = ["progress_message = ?"]
        vals = [message]
        for key in ("files_total", "files_processed", "has_report"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        if "run_dir" in kwargs:
            sets.append("run_dir = ?")
            vals.append(str(kwargs["run_dir"]))
        vals.append(run_id)
        conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def update_run_status(run_id: int, status: str, **kwargs):
    """Set the run status (running / completed / failed) and optional fields."""
    conn = get_db()
    try:
        sets = ["status = ?"]
        vals = [status]
        if status in ("completed", "failed"):
            sets.append("completed_at = ?")
            vals.append(datetime.now().isoformat())
        for key in ("files_total", "files_processed", "has_report"):
            if key in kwargs:
                sets.append(f"{key} = ?")
                vals.append(kwargs[key])
        if "run_dir" in kwargs:
            sets.append("run_dir = ?")
            vals.append(str(kwargs["run_dir"]))
        if "error" in kwargs:
            sets.append("error = ?")
            vals.append(str(kwargs["error"]))
        if "script_log" in kwargs:
            sets.append("script_log = ?")
            vals.append(str(kwargs["script_log"]))
        if "pdf_files" in kwargs:
            sets.append("pdf_files = ?")
            vals.append(_json.dumps(kwargs["pdf_files"]))
        if "progress_message" in kwargs:
            sets.append("progress_message = ?")
            vals.append(kwargs["progress_message"])
        vals.append(run_id)
        conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE id = ?", vals)
        conn.commit()
    finally:
        conn.close()


def get_run_record(run_id: int) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["pdf_files"] = _json.loads(d.get("pdf_files") or "[]")
        return d
    finally:
        conn.close()


def get_runs_for_user(user_id: int, limit: int = 200) -> list[dict]:
    """All runs for a user, newest first."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE user_id = ? ORDER BY started_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["pdf_files"] = _json.loads(d.get("pdf_files") or "[]")
            # Enrich with filesystem data for output counts
            if d["run_dir"]:
                rd = Path(d["run_dir"])
                d["output_count"] = len(list((rd / "outputs").iterdir())) if (rd / "outputs").exists() else 0
                d["has_report"] = int((rd / "outputs" / "result.md").exists())
                # Discover PDFs from disk if DB list is empty
                if not d["pdf_files"] and (rd / "outputs").exists():
                    d["pdf_files"] = [str(p) for p in (rd / "outputs").glob("*.pdf")]
            else:
                d["output_count"] = 0
            result.append(d)
        return result
    finally:
        conn.close()


def get_active_run_for_coworker(coworker_id: int) -> dict | None:
    """Return the currently running/pending/cancelling run for a coworker, if any."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE coworker_id = ? AND status IN ('pending', 'running', 'cancelling') ORDER BY started_at DESC LIMIT 1",
            (coworker_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["pdf_files"] = _json.loads(d.get("pdf_files") or "[]")
        return d
    finally:
        conn.close()


def count_active_runs(user_id: int) -> int:
    """Count runs that are pending/running/cancelling for the given user."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM runs WHERE user_id = ? AND status IN ('pending', 'running', 'cancelling')",
            (user_id,),
        ).fetchone()
        return int(row["n"]) if row else 0
    finally:
        conn.close()


def get_last_run_for_coworker(coworker_id: int) -> dict | None:
    """Return the most recent run (any status) for a coworker, or None."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE coworker_id = ? ORDER BY started_at DESC LIMIT 1",
            (coworker_id,),
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["pdf_files"] = _json.loads(d.get("pdf_files") or "[]")
        return d
    finally:
        conn.close()


def get_recent_runs_for_coworker(coworker_id: int, limit: int = 10) -> list[dict]:
    """Return the most recent N runs for a coworker, oldest-first (for sparkline)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE coworker_id = ? ORDER BY started_at DESC LIMIT ?",
            (coworker_id, limit),
        ).fetchall()
        result = [dict(r) for r in rows]
        result.reverse()  # oldest-first for left-to-right sparkline
        return result
    finally:
        conn.close()


def request_cancel_run(run_id: int) -> bool:
    """Mark a pending/running run as 'cancelling'. Returns True if updated."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "UPDATE runs SET status = 'cancelling', progress_message = 'Cancelling...' "
            "WHERE id = ? AND status IN ('pending', 'running')",
            (run_id,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def is_run_cancelling(run_id: int) -> bool:
    """Cheap check used by the executor between files."""
    conn = get_db()
    try:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        return bool(row and row["status"] == "cancelling")
    finally:
        conn.close()


def delete_runs(run_ids: list[int]):
    """Delete run records by id. Also removes run directories from disk."""
    if not run_ids:
        return
    conn = get_db()
    try:
        placeholders = ",".join("?" for _ in run_ids)
        # Fetch run dirs for filesystem cleanup
        rows = conn.execute(
            f"SELECT id, run_dir FROM runs WHERE id IN ({placeholders})", run_ids,
        ).fetchall()
        conn.execute(f"DELETE FROM runs WHERE id IN ({placeholders})", run_ids)
        conn.commit()
        # Remove filesystem dirs
        for row in rows:
            rd = row["run_dir"]
            if rd:
                p = Path(rd)
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
    finally:
        conn.close()


def clone_coworker(coworker_id: int, new_name: str, user_id: int) -> int:
    """Clone a coworker: copy DB record, prompt, skills, and input files."""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM coworkers WHERE id = ?", (coworker_id,)).fetchone()
        if not row:
            raise ValueError("CoWorker not found")
        src = dict(row)
        cursor = conn.execute(
            """INSERT INTO coworkers
               (name, job_description, workflow, status, model_provider, model_name, created_by)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (new_name, src["job_description"], src["workflow"], src["status"],
             src["model_provider"], src["model_name"], user_id),
        )
        conn.commit()
        new_id = cursor.lastrowid
    finally:
        conn.close()

    # Clone filesystem: create folders then copy process/ and inputs/
    create_coworker_folders(new_name)
    src_dir = get_coworker_dir(src["name"])
    dst_dir = get_coworker_dir(new_name)

    # Copy prompt
    src_prompt = src_dir / "process" / "prompt.md"
    if src_prompt.exists():
        shutil.copy2(src_prompt, dst_dir / "process" / "prompt.md")

    # Copy skills
    src_skills = src_dir / "process" / "skills"
    if src_skills.exists() and any(src_skills.iterdir()):
        shutil.copytree(src_skills, dst_dir / "process" / "skills", dirs_exist_ok=True)

    # Copy input files
    src_inputs = src_dir / "inputs"
    if src_inputs.exists():
        for f in src_inputs.iterdir():
            if f.is_file():
                shutil.copy2(f, dst_dir / "inputs" / f.name)

    return new_id


def get_run_stats_for_coworker(coworker_id: int) -> dict:
    """Return aggregate run stats for a coworker (for pipeline visualizer)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE coworker_id = ? ORDER BY started_at DESC",
            (coworker_id,),
        ).fetchall()
        runs = [dict(r) for r in rows]
        if not runs:
            return {"total": 0, "completed": 0, "failed": 0, "avg_files": 0, "avg_duration_s": 0}

        completed = [r for r in runs if r["status"] == "completed"]
        failed = [r for r in runs if r["status"] == "failed"]

        # Average files per run
        total_files = sum(r.get("files_total", 0) or 0 for r in runs)
        avg_files = total_files / len(runs) if runs else 0

        # Average duration for completed runs (seconds)
        durations = []
        for r in completed:
            sa = r.get("started_at", "")
            ca = r.get("completed_at", "")
            if sa and ca:
                try:
                    from datetime import datetime as _dt
                    start = _dt.fromisoformat(sa.replace("T", " ")[:19])
                    end = _dt.fromisoformat(ca.replace("T", " ")[:19])
                    durations.append((end - start).total_seconds())
                except (ValueError, TypeError):
                    pass
        avg_duration = sum(durations) / len(durations) if durations else 0

        # Per-file average (rough: total_duration / total_files for completed)
        total_completed_files = sum(r.get("files_total", 0) or 0 for r in completed)
        avg_per_file = sum(durations) / total_completed_files if total_completed_files else 0

        # Last failure info
        last_failure = failed[0] if failed else None
        last_failure_error = last_failure.get("error", "") if last_failure else ""
        last_failure_date = last_failure.get("started_at", "")[:10] if last_failure else ""

        return {
            "total": len(runs),
            "completed": len(completed),
            "failed": len(failed),
            "avg_files": round(avg_files, 1),
            "avg_duration_s": round(avg_duration, 1),
            "avg_per_file_s": round(avg_per_file, 1),
            "last_failure_error": last_failure_error,
            "last_failure_date": last_failure_date,
            "success_rate": round(len(completed) / len(runs) * 100) if runs else 0,
        }
    finally:
        conn.close()


# --- CoWorker feedback (Reward / Penalise / Suspend) ---

def create_feedback(
    coworker_id: int,
    coworker_name: str,
    user_id: int,
    feedback_type: str,
    content: str,
    reason: str = "",
) -> int:
    """Log a feedback entry for a CoWorker. feedback_type is 'reward' | 'penalise' | 'suspend'."""
    conn = get_db()
    try:
        cur = conn.execute(
            """INSERT INTO coworker_feedback
               (coworker_id, coworker_name, user_id, feedback_type, content, reason)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (coworker_id, coworker_name, user_id, feedback_type, content, reason),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_recent_feedback_all(user_id: int, limit: int = 10) -> list[dict]:
    """Get recent feedback entries across all CoWorkers for dashboard display."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM coworker_feedback
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_feedback_for_coworker(coworker_id: int, limit: int = 20) -> list[dict]:
    """Get feedback for a specific CoWorker."""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT * FROM coworker_feedback
               WHERE coworker_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (coworker_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --- Departments CRUD ---

def get_departments() -> list[dict]:
    """List all departments with member counts."""
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT d.*, COALESCE(cw.member_count, 0) AS member_count
            FROM departments d
            LEFT JOIN (
                SELECT workflow, COUNT(*) AS member_count
                FROM coworkers
                GROUP BY workflow
            ) cw ON cw.workflow = d.name
            ORDER BY d.name
        """).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_department_by_name(name: str) -> dict | None:
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM departments WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def create_department(name: str, icon: str = "work", color: str = "blue", description: str = "") -> int:
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO departments (name, icon, color, description) VALUES (?, ?, ?, ?)",
            (name.strip(), icon, color, description.strip()),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_department(
    dept_id: int,
    name: str,
    icon: str,
    color: str,
    description: str = "",
) -> None:
    """Update a department. If the name changes, cascade-update all CoWorker.workflow values."""
    conn = get_db()
    try:
        # Get existing name for rename detection
        row = conn.execute("SELECT name FROM departments WHERE id = ?", (dept_id,)).fetchone()
        if not row:
            raise ValueError(f"Department id={dept_id} not found")
        old_name = row["name"]
        new_name = name.strip()

        conn.execute(
            "UPDATE departments SET name = ?, icon = ?, color = ?, description = ? WHERE id = ?",
            (new_name, icon, color, description.strip(), dept_id),
        )
        # Cascade rename to existing CoWorkers
        if old_name != new_name:
            conn.execute(
                "UPDATE coworkers SET workflow = ? WHERE workflow = ?",
                (new_name, old_name),
            )
        conn.commit()
    finally:
        conn.close()


def delete_department(dept_id: int, reassign_to_name: str | None = None) -> None:
    """Delete a department. If it has CoWorkers and reassign_to_name is given,
    reassign them first. Otherwise, raises ValueError."""
    conn = get_db()
    try:
        row = conn.execute("SELECT name FROM departments WHERE id = ?", (dept_id,)).fetchone()
        if not row:
            raise ValueError(f"Department id={dept_id} not found")
        dept_name = row["name"]

        member_count = conn.execute(
            "SELECT COUNT(*) FROM coworkers WHERE workflow = ?",
            (dept_name,),
        ).fetchone()[0]

        if member_count > 0:
            if not reassign_to_name:
                raise ValueError(
                    f"Department '{dept_name}' has {member_count} CoWorker(s). "
                    f"Pass reassign_to_name to reassign before deleting."
                )
            conn.execute(
                "UPDATE coworkers SET workflow = ? WHERE workflow = ?",
                (reassign_to_name, dept_name),
            )

        conn.execute("DELETE FROM departments WHERE id = ?", (dept_id,))
        conn.commit()
    finally:
        conn.close()


def set_coworker_status(coworker_id: int, status: str) -> None:
    """Update only the status field of a CoWorker (used by suspend/activate)."""
    conn = get_db()
    try:
        conn.execute(
            "UPDATE coworkers SET status = ? WHERE id = ?",
            (status, coworker_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_runs(user_id: int) -> list[dict]:
    """Return all runs for a user from the DB, newest first.

    Falls back to filesystem scan for runs without DB records.
    """
    db_runs = get_runs_for_user(user_id)
    if db_runs:
        return db_runs

    # Fallback: scan filesystem for legacy runs
    coworkers = get_coworkers(user_id)
    all_runs = []
    for cw in coworkers:
        runs_dir = get_coworker_dir(cw["name"]) / "runs"
        if not runs_dir.exists():
            continue
        for d in runs_dir.iterdir():
            if not d.is_dir():
                continue
            input_count = len(list((d / "inputs").iterdir())) if (d / "inputs").exists() else 0
            output_count = len(list((d / "outputs").iterdir())) if (d / "outputs").exists() else 0
            has_report = (d / "outputs" / "result.md").exists()
            pdf_files = list((d / "outputs").glob("*.pdf")) if (d / "outputs").exists() else []
            all_runs.append({
                "id": None,
                "coworker_id": cw["id"],
                "coworker_name": cw["name"],
                "user_id": user_id,
                "model_provider": cw["model_provider"],
                "model_name": cw["model_name"],
                "workflow": cw["workflow"],
                "run_dir": str(d),
                "status": "completed",
                "progress_message": "",
                "files_total": input_count,
                "files_processed": input_count,
                "has_report": int(has_report),
                "pdf_files": [str(p) for p in pdf_files],
                "error": "",
                "started_at": d.name,  # timestamp folder name
                "completed_at": d.name,
                "output_count": output_count,
            })
    all_runs.sort(key=lambda r: r["started_at"], reverse=True)
    return all_runs
