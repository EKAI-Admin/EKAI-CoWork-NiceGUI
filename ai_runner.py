"""AI processing engine for CoWorker runs.

Reads input files + prompt from a run directory, sends them to Claude or Ollama,
and writes the response to outputs/result.md.

Supports text files, PDFs, and images (png, jpg, gif, webp).
"""

import base64
import mimetypes
import shutil
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


# --- Claude ---

def _call_claude_single(model: str, prompt: str, file: dict) -> str:
    """Send prompt + one file to Claude API using native multimodal content blocks."""
    client = anthropic.Anthropic()
    content_blocks = _build_claude_blocks_single(prompt, file)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content_blocks}],
    )
    return message.content[0].text


# --- Ollama ---

def _call_ollama_single(model: str, prompt: str, file: dict, base_url: str) -> str:
    """Send prompt + one file to Ollama API."""
    text_message = _build_text_message_single(prompt, file)

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": text_message}],
        "stream": False,
    }
    if file["type"] == "image":
        payload["messages"][0]["images"] = [file["data"]]

    response = httpx.post(
        f"{base_url.rstrip('/')}/api/chat",
        json=payload,
        timeout=300.0,
    )
    response.raise_for_status()
    return response.json()["message"]["content"]


# --- Public API ---

def process_run(
    coworker: dict,
    run_dir: Path,
    ollama_base_url: str = "http://localhost:11434",
    on_file_done: callable = None,
) -> Path:
    """Process a run: loop over each input file, call AI individually, append to result.

    Each file is sent to the AI model separately with the same prompt.
    All analyses are combined into a single result.md.

    Args:
        coworker: dict with keys 'name', 'model_provider', 'model_name'
        run_dir: Path to the timestamped run directory
        ollama_base_url: Ollama server URL (only used if provider is 'ollama')
        on_file_done: optional callback(file_index, total, filename) for progress

    Returns:
        Path to the output result.md file
    """
    prompt_file = run_dir / "process" / "prompt.md"
    if not prompt_file.exists():
        raise ValueError("No prompt.md found in run directory.")
    prompt = prompt_file.read_text().strip()
    if not prompt:
        raise ValueError("prompt.md is empty.")

    files = _read_input_files(run_dir / "inputs")
    if not files:
        raise ValueError("No input files found in run directory.")

    provider = coworker["model_provider"]
    model = coworker["model_name"]
    name = coworker["name"]

    # Process each file individually
    file_results = []
    for i, f in enumerate(files):
        if provider == "claude":
            response = _call_claude_single(model, prompt, f)
        elif provider == "ollama":
            response = _call_ollama_single(model, prompt, f, ollama_base_url)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        file_results.append({
            "name": f["name"],
            "type": f["type"],
            "response": response,
        })

        if on_file_done:
            on_file_done(i + 1, len(files), f["name"])

    coworker_outputs_dir = run_dir.parent.parent / "outputs"

    output_file = _write_result(
        run_dir, name, provider, model, files, file_results, coworker_outputs_dir,
    )
    return output_file
