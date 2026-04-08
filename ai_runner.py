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


def _build_text_message(prompt: str, files: list[dict]) -> str:
    """Build a plain-text message for providers that don't support multimodal."""
    parts = [prompt, "", "---", ""]
    for f in files:
        if f["type"] == "text":
            parts.append(f"## File: {f['name']}")
            parts.append(f"```\n{f['content']}\n```")
            parts.append("")
        else:
            parts.append(f"## File: {f['name']}")
            parts.append(f"[{f['type'].upper()} file — sent as attachment]")
            parts.append("")
    return "\n".join(parts)


def _build_claude_content_blocks(prompt: str, files: list[dict]) -> list[dict]:
    """Build Claude API content blocks with native image/PDF support."""
    blocks = []

    # Prompt as text block
    blocks.append({"type": "text", "text": prompt + "\n\n---\n"})

    for f in files:
        if f["type"] == "image":
            # File label
            blocks.append({"type": "text", "text": f"## File: {f['name']}"})
            # Native image block
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": f["media_type"],
                    "data": f["data"],
                },
            })
        elif f["type"] == "pdf":
            # File label
            blocks.append({"type": "text", "text": f"## File: {f['name']}"})
            # Native PDF document block
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": f["data"],
                },
            })
        else:
            # Text file as code block
            blocks.append({
                "type": "text",
                "text": f"## File: {f['name']}\n```\n{f['content']}\n```\n",
            })

    return blocks


def _write_result(
    run_dir: Path,
    coworker_name: str,
    provider: str,
    model_name: str,
    files: list[dict],
    response_text: str,
    coworker_outputs_dir: Path,
) -> Path:
    """Write the AI response to outputs/result.md with metadata header."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    file_list = ", ".join(f"{f['name']} ({f['type']})" for f in files)

    content = (
        f"# Run Output — {coworker_name}\n"
        f"**Model**: {provider}:{model_name}  \n"
        f"**Timestamp**: {timestamp}  \n"
        f"**Input Files**: {file_list}\n"
        f"\n---\n\n"
        f"{response_text}\n"
    )

    output_file = run_dir / "outputs" / "result.md"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(content)

    # Also copy to the coworker's top-level outputs folder
    coworker_outputs_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(output_file, coworker_outputs_dir / "result.md")

    return output_file


# --- Claude ---

def _call_claude(model: str, prompt: str, files: list[dict]) -> str:
    """Send prompt + files to Claude API using native multimodal content blocks."""
    client = anthropic.Anthropic()
    content_blocks = _build_claude_content_blocks(prompt, files)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": content_blocks}],
    )
    return message.content[0].text


# --- Ollama ---

def _call_ollama(model: str, prompt: str, files: list[dict], base_url: str) -> str:
    """Send prompt + files to Ollama API.

    For multimodal models (llava, etc.), images are sent via the 'images' field.
    PDFs are sent as text descriptions since Ollama doesn't natively support PDFs.
    """
    text_message = _build_text_message(prompt, files)

    # Collect base64 images for Ollama's multimodal support
    images = [f["data"] for f in files if f["type"] == "image"]

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": text_message}],
        "stream": False,
    }
    if images:
        payload["messages"][0]["images"] = images

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
) -> Path:
    """Process a run: read inputs + prompt, call AI, write result.

    Supports text files, images (png/jpg/gif/webp), and PDFs.
    Claude gets native multimodal content blocks.
    Ollama gets images via the images field for multimodal models.

    Args:
        coworker: dict with keys 'name', 'model_provider', 'model_name'
        run_dir: Path to the timestamped run directory
        ollama_base_url: Ollama server URL (only used if provider is 'ollama')

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

    if provider == "claude":
        response_text = _call_claude(model, prompt, files)
    elif provider == "ollama":
        response_text = _call_ollama(model, prompt, files, ollama_base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    coworker_outputs_dir = run_dir.parent.parent / "outputs"

    output_file = _write_result(
        run_dir, name, provider, model, files, response_text, coworker_outputs_dir,
    )
    return output_file
