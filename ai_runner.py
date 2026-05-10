"""AI processing engine for CoWorker runs.

Reads input files + prompt from a run directory, sends them to Claude or Ollama,
and writes the response to outputs/result.md.

Supports text files, PDFs, and images (png, jpg, gif, webp).
"""

import base64
import json
import mimetypes
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic
import httpx


# File type classification
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
PDF_EXTENSIONS = {".pdf"}
IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def _classify_file(path: Path) -> str:
    """Return 'image', 'pdf', or 'text' based on file extension."""
    ext = path.suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in PDF_EXTENSIONS:
        return "pdf"
    return "text"


def _read_input_files(inputs_dir: Path) -> list[dict]:
    """Read all files from the inputs directory.

    Returns list of dicts with keys:
      - name: filename
      - type: 'text', 'image', or 'pdf'
      - content: text content (for text files)
      - data: base64-encoded bytes (for images and PDFs)
      - media_type: MIME type (for images and PDFs)
    """
    files = []
    if not inputs_dir.exists():
        return files
    for f in sorted(inputs_dir.iterdir()):
        if not f.is_file():
            continue
        file_type = _classify_file(f)
        entry = {"name": f.name, "type": file_type}

        if file_type == "image":
            entry["data"] = base64.standard_b64encode(f.read_bytes()).decode()
            entry["media_type"] = IMAGE_MEDIA_TYPES.get(f.suffix.lower(), "image/png")
        elif file_type == "pdf":
            entry["data"] = base64.standard_b64encode(f.read_bytes()).decode()
            entry["media_type"] = "application/pdf"
        else:
            try:
                entry["content"] = f.read_text(errors="replace")
            except Exception:
                entry["content"] = f"[Binary file — {f.stat().st_size} bytes]"

        files.append(entry)
    return files


def _build_text_message_single(prompt: str, file: dict) -> str:
    """Build a plain-text message for a single file (Ollama)."""
    parts = [prompt, "", "---", "", f"## File: {file['name']}"]
    if file["type"] == "text":
        parts.append(f"```\n{file['content']}\n```")
    else:
        parts.append(f"[{file['type'].upper()} file — sent as attachment]")
    return "\n".join(parts)


def _build_claude_blocks_single(prompt: str, file: dict) -> list[dict]:
    """Build Claude API content blocks for a single file."""
    blocks = [{"type": "text", "text": prompt + f"\n\n---\n\n## File: {file['name']}"}]

    if file["type"] == "image":
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": file["media_type"],
                "data": file["data"],
            },
        })
    elif file["type"] == "pdf":
        blocks.append({
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": file["data"],
            },
        })
    else:
        blocks.append({
            "type": "text",
            "text": f"```\n{file['content']}\n```",
        })

    return blocks


def _write_result(
    run_dir: Path,
    coworker_name: str,
    provider: str,
    model_name: str,
    files: list[dict],
    file_results: list[dict],
    coworker_outputs_dir: Path,
) -> Path:
    """Write per-file AI analyses to outputs/result.md.

    Args:
        file_results: list of dicts with 'name', 'type', 'response' keys.
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_list = ", ".join(f"{f['name']} ({f['type']})" for f in files)

    sections = [
        f"# Run Output — {coworker_name}",
        f"**Model**: {provider}:{model_name}  ",
        f"**Timestamp**: {timestamp}  ",
        f"**Input Files**: {file_list}  ",
        f"**Files Processed**: {len(file_results)}",
        "",
        "---",
        "",
    ]

    for i, fr in enumerate(file_results, 1):
        sections.append(f"## {i}. {fr['name']} ({fr['type']})")
        sections.append("")
        sections.append(fr["response"])
        sections.append("")
        sections.append("---")
        sections.append("")

    content = "\n".join(sections)

    output_file = run_dir / "outputs" / "result.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content)

    # Also copy to the coworker's top-level outputs folder
    coworker_outputs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_file, coworker_outputs_dir / "result.md")

    return output_file


# --- Skills ---

def load_coworker_skills_content(coworker_dir: Path) -> str:
    """Load skill content from a coworker's process/skills/ folder (no run_dir needed)."""
    skills_dir = coworker_dir / "process" / "skills"
    if not skills_dir.exists():
        return ""
    parts = []
    for skill_folder in sorted(skills_dir.iterdir()):
        if not skill_folder.is_dir():
            continue
        for f in sorted(skill_folder.rglob("*")):
            if f.is_file() and f.suffix.lower() in {".md", ".txt", ".json"}:
                try:
                    content = f.read_text(errors="replace")
                    rel = f.relative_to(skills_dir)
                    parts.append(f"# Skill: {rel}\n\n{content}")
                except Exception:
                    continue
    return "\n\n---\n\n".join(parts)


def build_coworker_chat_context(coworker: dict, user_id: int, max_report_chars: int = 2500) -> str:
    """Assemble a rich system prompt from DB + filesystem state so the chat has
    full awareness of the CoWorker's identity, workflow, recent runs, outputs,
    inputs, and team feedback.

    Safe to call from a background thread — this reads only; no writes.
    """
    # Lazy imports to avoid circular references
    from db import (
        get_prompt, get_coworker_dir,
        get_run_stats_for_coworker, get_recent_runs_for_coworker,
        get_feedback_for_coworker, load_coworker_skill_manifest,
    )

    name = coworker["name"]
    cw_dir = get_coworker_dir(name)
    parts: list[str] = []

    # --- Identity ---
    parts.append(
        f"You are **{name}**, an AI CoWorker in the EKAI CoWork platform. "
        f"Your role is: {coworker.get('job_description', '(not specified)')}. "
        f"You belong to the **{coworker.get('workflow') or 'Unassigned'}** department. "
        f"You run on **{coworker.get('model_provider')}:{coworker.get('model_name')}**. "
        f"Current status: **{coworker.get('status', 'active')}**."
    )

    # --- Workflow prompt (how you process inputs) ---
    prompt_text = get_prompt(name) or ""
    if prompt_text.strip():
        parts.append(
            "## Your workflow prompt (how you process each input file)\n\n"
            f"```\n{prompt_text.strip()}\n```"
        )

    # --- Skills ---
    skills_ctx = load_coworker_skills_content(cw_dir)
    manifest = load_coworker_skill_manifest(name)
    if manifest:
        pipeline = manifest.get("pipeline") or []
        mf_line = f"**Skill bundle**: `{manifest['name']}`"
        if manifest.get("description"):
            mf_line += f" — {manifest['description']}"
        if pipeline:
            steps = " → ".join(s.get("step", "?") for s in pipeline)
            mf_line += f"\n**Pipeline**: {steps}"
        parts.append("## Skills available to you\n\n" + mf_line)
    if skills_ctx:
        # Cap skills content so we don't blow the context window
        capped = skills_ctx if len(skills_ctx) < 6000 else skills_ctx[:6000] + "\n\n... (truncated)"
        parts.append("### Skill content\n\n" + capped)

    # --- Inputs currently queued ---
    inputs_dir = cw_dir / "inputs"
    if inputs_dir.exists():
        files = sorted(f for f in inputs_dir.iterdir() if f.is_file())
        if files:
            rows = []
            for f in files[:30]:
                kb = f.stat().st_size / 1024
                rows.append(f"- `{f.name}` ({kb:.1f} KB)")
            if len(files) > 30:
                rows.append(f"- ... and {len(files) - 30} more files")
            parts.append(f"## Input files queued ({len(files)})\n\n" + "\n".join(rows))
        else:
            parts.append("## Input files queued\n\n(none — the inputs folder is empty)")

    # --- Run activity ---
    stats = get_run_stats_for_coworker(coworker["id"])
    if stats.get("total", 0) > 0:
        summary = (
            f"- Total runs: **{stats['total']}**\n"
            f"- Completed: **{stats.get('completed', 0)}** | Failed: **{stats.get('failed', 0)}**\n"
            f"- Success rate: **{stats.get('success_rate', 0)}%**\n"
            f"- Average duration: **{stats.get('avg_duration_s', 0)}s** "
            f"(~{stats.get('avg_per_file_s', 0)}s per file)\n"
            f"- Average files per run: **{stats.get('avg_files', 0)}**"
        )
        if stats.get("last_failure_error"):
            summary += f"\n- Last failure ({stats.get('last_failure_date','')}): {stats['last_failure_error'][:200]}"
        parts.append("## Your recent activity\n\n" + summary)
    else:
        parts.append("## Your recent activity\n\nYou have not been run yet.")

    # --- Recent runs (compact list) ---
    recent = get_recent_runs_for_coworker(coworker["id"], limit=5)
    if recent:
        rows = []
        for r in recent:
            ts = (r.get("started_at") or "")[:19].replace("T", " ")
            status = r.get("status", "?")
            ft = r.get("files_total", 0) or 0
            fp = r.get("files_processed", 0) or 0
            line = f"- {ts} — **{status}** ({fp}/{ft} files)"
            if status == "failed" and r.get("error"):
                line += f"  — {r['error'][:120]}"
            rows.append(line)
        parts.append("## Last 5 runs\n\n" + "\n".join(rows))

    # --- Latest output (result.md) ---
    outputs_dir = cw_dir / "outputs"
    result_md = outputs_dir / "result.md"
    if result_md.exists():
        try:
            text = result_md.read_text(errors="replace")
            if text.strip():
                snippet = text if len(text) <= max_report_chars else text[:max_report_chars] + "\n\n... (truncated)"
                parts.append(
                    f"## Your latest analysis report (result.md, {len(text)} chars)\n\n"
                    f"```markdown\n{snippet}\n```"
                )
        except Exception:
            pass
    # Plus any PDFs / supporting output files
    if outputs_dir.exists():
        other_files = sorted(
            f for f in outputs_dir.iterdir()
            if f.is_file() and f.name != "result.md"
        )
        if other_files:
            rows = [f"- `{f.name}` ({f.stat().st_size / 1024:.1f} KB)" for f in other_files[:20]]
            parts.append("### Additional output files\n\n" + "\n".join(rows))

    # --- Team feedback (Reward / Penalise / Suspend) ---
    feedback = get_feedback_for_coworker(coworker["id"], limit=6)
    if feedback:
        rows = []
        for fb in feedback:
            kind = fb.get("feedback_type", "?")
            marker = {"reward": "⭐ REWARD", "penalise": "⚠ IMPROVE", "suspend": "⏸ SUSPENDED"}.get(kind, kind.upper())
            ts = (fb.get("created_at") or "")[:10]
            content = (fb.get("content") or "").strip()
            snippet = content if len(content) < 200 else content[:200] + "…"
            line = f"- [{ts}] {marker}: {snippet}"
            rows.append(line)
        parts.append("## Recent team feedback on your work\n\n" + "\n".join(rows))

    # --- Guidance for answering ---
    parts.append(
        "## How to respond to the user\n\n"
        "- Be concise, direct, and professional — you're working with a teammate.\n"
        "- Reference concrete numbers and file names from the context above when relevant.\n"
        "- If asked about your own performance, speak in the first person (\"I completed X runs this week…\").\n"
        "- If a question falls outside your scope/context, say so honestly and suggest who or what could help.\n"
        "- Use markdown formatting (lists, bold, code) where it improves readability."
    )

    return "\n\n".join(parts)


def _load_skills(run_dir: Path) -> str:
    """Read all skill files from run_dir/process/skills/<skill-name>/ folders.

    Returns the text content of all skill files concatenated as system context.
    """
    skills_dir = run_dir / "process" / "skills"
    if not skills_dir.exists():
        return ""
    parts = []
    for skill_folder in sorted(skills_dir.iterdir()):
        if not skill_folder.is_dir():
            continue
        for f in sorted(skill_folder.rglob("*")):
            if f.is_file():
                try:
                    content = f.read_text(errors="replace")
                    rel = f.relative_to(skills_dir)
                    parts.append(f"# Skill: {rel}\n\n{content}")
                except Exception:
                    continue
    return "\n\n---\n\n".join(parts)


def _find_skill_dir(run_dir: Path) -> Path | None:
    """Find the first skill folder that contains a skill.json manifest."""
    skills_dir = run_dir / "process" / "skills"
    if not skills_dir.exists():
        return None
    for skill_folder in sorted(skills_dir.iterdir()):
        if not skill_folder.is_dir():
            continue
        # Check this folder and one level deeper (handles double-nested zip extraction)
        for candidate in [skill_folder, *sorted(skill_folder.iterdir())]:
            if candidate.is_dir() and (candidate / "skill.json").exists():
                return candidate
    return None


def _find_claude_skill_dir(run_dir: Path) -> Path | None:
    """Find a Claude skill bundle (SKILL.md + scripts/ folder, no skill.json).

    This is the Anthropic Claude skill format: a folder with SKILL.md (with
    YAML frontmatter) and a scripts/ subfolder containing executable .py files.
    """
    skills_dir = run_dir / "process" / "skills"
    if not skills_dir.exists():
        return None
    for skill_folder in sorted(skills_dir.iterdir()):
        if not skill_folder.is_dir():
            continue
        for candidate in [skill_folder, *sorted(skill_folder.iterdir())]:
            if not candidate.is_dir():
                continue
            has_skill_md = (candidate / "SKILL.md").exists()
            scripts_dir = candidate / "scripts"
            has_scripts = scripts_dir.is_dir() and any(
                p.suffix == ".py" for p in scripts_dir.iterdir() if p.is_file()
            )
            if has_skill_md and has_scripts:
                return candidate
    return None


def _parse_skill_md_frontmatter_simple(md_path: Path) -> dict:
    """Minimal YAML frontmatter parser for SKILL.md (name/description only)."""
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
    folded: list[str] = []
    for line in block.splitlines():
        if current_key is not None and (line.startswith(" ") or line.startswith("\t")):
            folded.append(line.strip())
            continue
        if current_key is not None:
            result[current_key] = " ".join(folded).strip()
            current_key, folded = None, []
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if value in (">", "|", ""):
            current_key = key
            folded = []
        else:
            result[key] = value.strip('"').strip("'")
    if current_key is not None:
        result[current_key] = " ".join(folded).strip()
    return result


_CLAUDE_USAGE_RE = re.compile(
    r"python\s+(?:scripts/)?(?P<script>[a-zA-Z0-9_\-/]+\.py)(?P<args>[^\n`]*)",
)


def _translate_claude_arg(arg: str, skill_dir: Path, outputs_dir: Path, inputs_dir: Path) -> str:
    """Translate Claude-skill-style arg paths to engine placeholder paths.

    Converts common Anthropic conventions:
      assets/X, references/X     → {skill_dir}/assets/X (or references/X)
      /tmp/X.json, /tmp/X.pdf    → {outputs}/X.json (scratch paths become run outputs)
      <output folder>/X          → {outputs}/X
      path/to/keywords.txt       → {skill_dir}/assets/default_keywords.txt (best-effort)
      <YYYY-MM-DD>, <HHMM>       → substituted with current date/time
    """
    # Strip markdown code-fence residue (backticks/quotes) at either end
    arg = arg.strip("`\"'")

    # Substitute date/time template tokens
    now = datetime.now()
    arg = arg.replace("<YYYY-MM-DD>", now.strftime("%Y-%m-%d"))
    arg = arg.replace("<HHMM>", now.strftime("%H%M"))
    arg = arg.replace("<HH-MM>", now.strftime("%H-%M"))

    # Skip if arg is a flag (starts with -) or looks like a number
    if arg.startswith("-") or arg.replace(".", "").isdigit():
        return arg

    # <output folder>/... or <outputs>/...
    if arg.startswith("<") and ">" in arg and "/" in arg:
        tail = arg.split(">", 1)[1].lstrip("/")
        return str(outputs_dir / tail)

    # Scratch paths like /tmp/foo.json — redirect to outputs so artifacts persist
    if arg.startswith("/tmp/"):
        return str(outputs_dir / Path(arg).name)

    # Skill-relative paths (assets/X, references/X, scripts/X)
    for prefix in ("assets/", "references/", "scripts/"):
        if arg.startswith(prefix):
            return str(skill_dir / arg)

    # Placeholder-style paths like "path/to/keywords.txt" — look for a
    # real bundled asset with the same basename.
    if "/" in arg and arg.startswith(("path/to/", "your/", "<path>")):
        basename = Path(arg).name
        candidate = skill_dir / "assets" / basename
        if candidate.exists():
            return str(candidate)
        # Best-guess: default_<basename>
        alt = skill_dir / "assets" / f"default_{basename}"
        if alt.exists():
            return str(alt)

    # "keywords.txt" or similar bare filename → try skill_dir/assets first
    if "/" not in arg and "." in arg and not arg.startswith("."):
        candidate = skill_dir / "assets" / arg
        if candidate.exists():
            return str(candidate)
        if arg == "keywords.txt":
            alt = skill_dir / "assets" / "default_keywords.txt"
            if alt.exists():
                return str(alt)

    return arg


def _synthesize_claude_manifest(skill_dir: Path, outputs_dir: Path, inputs_dir: Path) -> dict | None:
    """Auto-synthesize a pipeline manifest from a Claude skill bundle.

    Strategy: scan SKILL.md for 'python <script> ...' invocations in the
    order they appear, translate path conventions, and build a pipeline.
    Falls back to alphabetical script execution if no Usage examples found.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None

    front = _parse_skill_md_frontmatter_simple(skill_md)
    md_text = skill_md.read_text()

    # Strip frontmatter before parsing usage examples
    body = md_text
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end != -1:
            body = body[end + 4:]

    pipeline: list[dict] = []
    seen_scripts: set[str] = set()
    scripts_dir = skill_dir / "scripts"

    # Parse "python scripts/X.py --flag value ..." lines from SKILL.md body
    for match in _CLAUDE_USAGE_RE.finditer(body):
        script_rel = match.group("script")
        if not script_rel.startswith("scripts/"):
            script_rel = f"scripts/{script_rel}"
        if script_rel in seen_scripts:
            continue
        script_path = skill_dir / script_rel
        if not script_path.exists():
            continue
        seen_scripts.add(script_rel)

        # Parse args. Merge tokens inside unclosed angle-bracket placeholders
        # like `<output folder>/foo.pdf` which would otherwise split on the space.
        raw_tokens = match.group("args").strip().split()
        merged_args: list[str] = []
        buffer = ""
        for tok in raw_tokens:
            if buffer:
                buffer += " " + tok
                if ">" in tok:
                    merged_args.append(buffer)
                    buffer = ""
            elif "<" in tok and ">" not in tok:
                buffer = tok
            else:
                merged_args.append(tok)
        if buffer:  # unclosed — take as-is
            merged_args.append(buffer)

        translated = [
            _translate_claude_arg(a, skill_dir, outputs_dir, inputs_dir) for a in merged_args
        ]
        step_name = Path(script_rel).stem.replace("_", "-")
        pipeline.append({
            "step": step_name,
            "script": script_rel,
            "args": translated,
        })

    # Fallback: no usage examples found → run all scripts alphabetically with no args
    if not pipeline and scripts_dir.is_dir():
        for py in sorted(scripts_dir.glob("*.py")):
            pipeline.append({
                "step": py.stem.replace("_", "-"),
                "script": f"scripts/{py.name}",
                "args": [],
            })

    if not pipeline:
        return None

    return {
        "name": front.get("name", skill_dir.name),
        "description": front.get("description", ""),
        "pipeline": pipeline,
        "_skill_dir": skill_dir,
        "_source": "claude-skill-auto",
    }


def load_skill_manifest(run_dir: Path) -> dict | None:
    """Load and validate a skill manifest from the run's skill folder.

    Tries in order:
      1. skill.json with a "pipeline" list (native format)
      2. Claude skill format (SKILL.md + scripts/) → auto-synthesized manifest

    Returns the manifest dict with an added '_skill_dir' key, or None.
    """
    # Try native skill.json first
    skill_dir = _find_skill_dir(run_dir)
    if skill_dir:
        manifest_path = skill_dir / "skill.json"
        try:
            manifest = json.loads(manifest_path.read_text())
            if "pipeline" in manifest and isinstance(manifest["pipeline"], list):
                manifest["_skill_dir"] = skill_dir
                return manifest
        except (json.JSONDecodeError, OSError):
            pass

    # Fall back: Claude skill format auto-synthesis
    claude_dir = _find_claude_skill_dir(run_dir)
    if claude_dir:
        outputs_dir = run_dir / "outputs"
        inputs_dir = run_dir / "inputs"
        synth = _synthesize_claude_manifest(claude_dir, outputs_dir, inputs_dir)
        if synth:
            return synth

    return None


def _build_extraction_prompt(rules_file: Path, files: list[dict]) -> str:
    """Build a prompt asking the AI to extract structured fields per the rules JSON.

    Reads the rules file to discover document types and required fields,
    then constructs a prompt that requests JSON output per file.
    """
    rules = json.loads(rules_file.read_text())
    checklist = rules.get("document_checklist", [])
    individual_rules = rules.get("individual_rules", {})

    doc_types = []
    for item in checklist:
        doc_id = item["doc_id"]
        desc = item.get("description", item["name"])
        fields_needed = []
        if doc_id in individual_rules:
            for rule in individual_rules[doc_id].get("rules", []):
                field = rule.get("field", "")
                if field and field not in fields_needed:
                    fields_needed.append(field)
        doc_types.append(
            f"  - {doc_id}: {desc}\n"
            f"    Fields to extract: {', '.join(fields_needed) if fields_needed else 'classify only'}"
        )

    file_list = "\n".join(f"  - {f['name']}" for f in files)

    return f"""You are a document classification and extraction engine.

Analyze the document and:
1. Classify it as one of these document types:
{chr(10).join(doc_types)}

2. Extract ALL the fields listed for that document type.

The files being processed are:
{file_list}

IMPORTANT: Respond with ONLY valid JSON (no markdown fences, no explanation). Use this exact format:
{{
    "doc_id": "THE_DOC_ID",
    "file": "filename.pdf",
    "fields": {{
        "field_name": "extracted value",
        ...
    }}
}}

For dates, use ISO format (YYYY-MM-DD).
For boolean checks (signature present, photo present), use true/false.
If a field cannot be determined, use null.
"""


def _extract_json_from_response(response: str) -> dict | None:
    """Try to parse JSON from an AI response, handling markdown fences."""
    text = response.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                return None
    return None


def _run_extraction(
    manifest: dict,
    run_dir: Path,
    provider: str,
    model: str,
    files: list[dict],
    ollama_base_url: str,
    on_status: callable = None,
) -> Path:
    """AI extraction pass: send each file to the model for structured field extraction.

    Uses the rules JSON declared in manifest["extraction"]["rules"] to build the
    extraction prompt. Returns the path to the saved extractions.json.
    """
    skill_dir = manifest["_skill_dir"]
    rules_rel = manifest.get("extraction", {}).get("rules", "")
    rules_file = skill_dir / rules_rel
    if not rules_file.exists():
        raise RuntimeError(f"Rules file not found: {rules_rel}")

    extraction_prompt = _build_extraction_prompt(rules_file, files)
    documents = {}

    for i, f in enumerate(files):
        if on_status:
            on_status(f"Extracting fields from {f['name']} ({i + 1}/{len(files)})...")

        if provider == "claude":
            response = _call_claude_single(model, extraction_prompt, f)
        else:
            response = _call_ollama_single(model, extraction_prompt, f, ollama_base_url)

        doc_data = _extract_json_from_response(response)
        if doc_data and "doc_id" in doc_data:
            doc_id = doc_data["doc_id"]
            documents[doc_id] = {
                "file": f["name"],
                "fields": doc_data.get("fields", {}),
            }

    # Try to infer client name from any document's company_name field
    client_name = "Unknown"
    for doc in documents.values():
        name = doc.get("fields", {}).get("company_name")
        if name:
            client_name = name
            break

    extractions = {
        "client_name": client_name,
        "verification_date": datetime.now().date().isoformat(),
        "documents": documents,
    }

    extractions_path = run_dir / "outputs" / "extractions.json"
    extractions_path.parent.mkdir(parents=True, exist_ok=True)
    extractions_path.write_text(json.dumps(extractions, indent=2, default=str))
    return extractions_path


def _resolve_pipeline_arg(
    arg: str,
    placeholders: dict[str, str],
) -> str:
    """Replace {placeholder} tokens in a pipeline arg with actual paths."""
    for key, value in placeholders.items():
        arg = arg.replace(f"{{{key}}}", value)
    return arg


def run_skill_pipeline(
    run_dir: Path,
    manifest: dict,
    provider: str,
    model: str,
    files: list[dict],
    ollama_base_url: str = "http://localhost:11434",
    on_status: callable = None,
) -> tuple[list[Path], str]:
    """Execute a skill pipeline defined by a skill.json manifest.

    Flow:
      1. If manifest has "extraction", run AI extraction pass → extractions.json
      2. Walk manifest["pipeline"] steps in order, running each script via subprocess

    Placeholder tokens in pipeline args are resolved to real paths:
      {rules}        → the rules JSON from manifest.extraction.rules
      {extractions}  → outputs/extractions.json
      {results}      → outputs/results.json
      {report_pdf}   → outputs/<skill_name>_report.pdf
      {outputs}      → the run's outputs directory
      {skill_dir}    → the skill folder root

    Returns (list of output file paths, combined script log text).
    """
    skill_dir = manifest["_skill_dir"]
    skill_name = manifest.get("name", "skill")
    outputs_dir = run_dir / "outputs"
    outputs_dir.mkdir(parents=True, exist_ok=True)
    coworker_outputs = run_dir.parent.parent / "outputs"

    # --- Step 1: AI extraction (if declared) ---
    extraction_config = manifest.get("extraction")
    extractions_path = None
    if extraction_config and extraction_config.get("rules"):
        if on_status:
            on_status("Extracting structured data from documents...")
        extractions_path = _run_extraction(
            manifest, run_dir, provider, model, files, ollama_base_url, on_status,
        )

    # --- Build placeholder map ---
    rules_rel = (extraction_config or {}).get("rules", "")
    rules_path = skill_dir / rules_rel if rules_rel else ""

    placeholders = {
        "rules": str(rules_path),
        "extractions": str(extractions_path or ""),
        "results": str(outputs_dir / "results.json"),
        "report_pdf": str(outputs_dir / f"{skill_name}_report.pdf"),
        "outputs": str(outputs_dir),
        "skill_dir": str(skill_dir),
    }

    # --- Step 2: Execute pipeline steps ---
    python = sys.executable
    produced_files = []
    log_lines: list[str] = []

    # Enhanced subprocess env: expose standard paths + fix macOS SSL cert bundle
    import os
    sub_env = os.environ.copy()
    sub_env["SKILL_DIR"] = str(skill_dir)
    sub_env["RUN_DIR"] = str(run_dir)
    sub_env["RUN_INPUTS"] = str(run_dir / "inputs")
    sub_env["RUN_OUTPUTS"] = str(outputs_dir)
    try:
        import certifi
        sub_env.setdefault("SSL_CERT_FILE", certifi.where())
        sub_env.setdefault("REQUESTS_CA_BUNDLE", certifi.where())
    except ImportError:
        pass

    for step in manifest["pipeline"]:
        step_name = step.get("step", "unnamed")
        script_rel = step.get("script", "")
        script_path = skill_dir / script_rel

        if not script_path.exists():
            raise RuntimeError(f"Skill script not found: {script_rel}")

        if on_status:
            on_status(f"Running pipeline step: {step_name}...")

        # Resolve args
        raw_args = step.get("args", [])
        resolved_args = [_resolve_pipeline_arg(a, placeholders) for a in raw_args]

        cmd = [python, str(script_path)] + resolved_args
        log_lines.append(f"─── Step: {step_name} ───")
        log_lines.append(f"  cmd: {script_rel} {' '.join(resolved_args)}")
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120, env=sub_env,
            )
            # Always capture stdout/stderr regardless of exit code
            if proc.stdout.strip():
                log_lines.append(f"  [stdout]\n{proc.stdout.rstrip()}")
            if proc.stderr.strip():
                log_lines.append(f"  [stderr]\n{proc.stderr.rstrip()}")
            log_lines.append(f"  exit code: {proc.returncode}")

            if proc.returncode != 0:
                raise RuntimeError(
                    f"Step '{step_name}' failed (exit {proc.returncode}):\n{proc.stderr}"
                )
        except subprocess.TimeoutExpired:
            log_lines.append(f"  ⚠ TIMEOUT after 120s")
            raise RuntimeError(f"Step '{step_name}' timed out")

        # Track output files from this step's args (any resolved path in outputs/)
        for arg in resolved_args:
            p = Path(arg)
            if p.exists() and str(outputs_dir) in str(p):
                produced_files.append(p)

    script_log = "\n".join(log_lines)

    # --- Copy final outputs to coworker's top-level outputs ---
    coworker_outputs.mkdir(parents=True, exist_ok=True)
    for f in produced_files:
        shutil.copy2(f, coworker_outputs / f.name)

    return produced_files, script_log


# --- Claude ---

def _call_claude_single(model: str, prompt: str, file: dict, system: str = "", max_retries: int = 5) -> str:
    """Send prompt + one file to Claude API with retry on rate limits."""
    client = anthropic.Anthropic()
    content_blocks = _build_claude_blocks_single(prompt, file)

    kwargs = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content_blocks}],
    }
    if system:
        kwargs["system"] = system

    for attempt in range(max_retries):
        try:
            message = client.messages.create(**kwargs)
            return message.content[0].text
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt * 15  # 15s, 30s, 60s, 120s, 240s
            time.sleep(wait)


# --- Ollama ---

def _call_ollama_single(model: str, prompt: str, file: dict, base_url: str, system: str = "") -> str:
    """Send prompt + one file to Ollama API."""
    text_message = _build_text_message_single(prompt, file)

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": text_message})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if file["type"] == "image":
        payload["messages"][-1]["images"] = [file["data"]]

    response = httpx.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=600.0,
    )
    if response.status_code == 404:
        raise ValueError(f"Ollama model '{model}' not found. Pull it first: ollama pull {model}")
    response.raise_for_status()
    return response.json()["message"]["content"]


# --- Public API ---

def prepare_run(run_dir: Path) -> tuple[str, list[dict], str]:
    """Validate and load run inputs. Returns (prompt, files, skills_context)."""
    prompt_file = run_dir / "process" / "prompt.md"
    if not prompt_file.exists():
        raise ValueError("No prompt.md found in run directory.")
    prompt = prompt_file.read_text().strip()
    if not prompt:
        raise ValueError("prompt.md is empty.")

    files = _read_input_files(run_dir / "inputs")
    if not files:
        raise ValueError("No input files found in run directory.")

    skills_context = _load_skills(run_dir)
    return prompt, files, skills_context


def process_single_file(
    provider: str,
    model: str,
    prompt: str,
    file: dict,
    skills_context: str,
    ollama_base_url: str = "http://localhost:11434",
) -> dict:
    """Process one input file through the AI model. Returns result dict."""
    if provider == "claude":
        response = _call_claude_single(model, prompt, file, system=skills_context)
    elif provider == "ollama":
        response = _call_ollama_single(model, prompt, file, ollama_base_url, system=skills_context)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    return {"name": file["name"], "type": file["type"], "response": response}


def chat_with_coworker(
    provider: str,
    model: str,
    system_prompt: str,
    skills_context: str,
    history: list[dict],
    user_message: str,
    ollama_base_url: str = "http://localhost:11434",
) -> str:
    """Multi-turn chat with a CoWorker. Uses the coworker's prompt + skills as system context.

    history: list of {"role": "user"|"assistant", "content": str}
    Returns the assistant's reply text.
    """
    # Build combined system string: CoWorker's job prompt + skill content
    system = system_prompt
    if skills_context:
        system = f"{system_prompt}\n\n---\n\n{skills_context}" if system_prompt else skills_context

    messages = list(history) + [{"role": "user", "content": user_message}]

    if provider == "claude":
        client = anthropic.Anthropic()
        kwargs = {
            "model": model,
            "max_tokens": 2048,
            "messages": messages,
        }
        if system:
            kwargs["system"] = system
        resp = client.messages.create(**kwargs)
        return resp.content[0].text

    if provider == "ollama":
        ol_messages = []
        if system:
            ol_messages.append({"role": "system", "content": system})
        ol_messages.extend(messages)
        response = httpx.post(
            f"{ollama_base_url.rstrip('/')}/api/chat",
            json={"model": model, "messages": ol_messages, "stream": False},
            timeout=180.0,
        )
        if response.status_code == 404:
            raise ValueError(f"Ollama model '{model}' not found.")
        response.raise_for_status()
        return response.json()["message"]["content"]

    raise ValueError(f"Unknown provider: {provider}")


def finalize_run(
    run_dir: Path,
    coworker_name: str,
    provider: str,
    model: str,
    files: list[dict],
    file_results: list[dict],
) -> Path:
    """Write results to output file. Returns path to result.md."""
    coworker_outputs_dir = run_dir.parent.parent / "outputs"
    return _write_result(
        run_dir, coworker_name, provider, model, files, file_results, coworker_outputs_dir,
    )


def process_run(
    coworker: dict,
    run_dir: Path,
    ollama_base_url: str = "http://localhost:11434",
    on_file_done: callable = None,
) -> Path:
    """Process a full run (convenience wrapper). For UI progress, use the step functions instead."""
    prompt, files, skills_context = prepare_run(run_dir)

    provider = coworker["model_provider"]
    model = coworker["model_name"]

    file_results = []
    for i, f in enumerate(files):
        result = process_single_file(provider, model, prompt, f, skills_context, ollama_base_url)
        file_results.append(result)
        if on_file_done:
            on_file_done(i + 1, len(files), f["name"])

    return finalize_run(run_dir, coworker["name"], provider, model, files, file_results)
