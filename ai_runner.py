"""AI processing engine for CoWorker runs.

Reads input files + prompt from a run directory, sends them to Claude or Ollama,
and writes the response to outputs/result.md.
"""

import shutil
from datetime import datetime
from pathlib import Path

import anthropic
import httpx


def _read_input_files(inputs_dir: Path) -> list[dict]:
    """Read all files from the inputs directory.

    Returns list of dicts with 'name' and 'content' keys.
    """
    files = []
    if not inputs_dir.exists():
        return files
    for f in sorted(inputs_dir.iterdir()):
        if f.is_file():
            try:
                content = f.read_text(errors="replace")
            except Exception:
                content = f"[Binary file — {f.stat().st_size} bytes]"
            files.append({"name": f.name, "content": content})
    return files


def _build_user_message(prompt: str, files: list[dict]) -> str:
    """Combine the prompt and all input file contents into a single user message."""
    parts = [prompt, "", "---", ""]
    for f in files:
        parts.append(f"## File: {f['name']}")
        parts.append(f"```\n{f['content']}\n```")
        parts.append("")
    return "\n".join(parts)


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
    file_list = ", ".join(f["name"] for f in files)

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
    """Send prompt + files to Claude API and return the response text."""
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    user_message = _build_user_message(prompt, files)

    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": user_message}],
    )
    return message.content[0].text


# --- Ollama ---

def _call_ollama(model: str, prompt: str, files: list[dict], base_url: str) -> str:
    """Send prompt + files to Ollama API and return the response text."""
    user_message = _build_user_message(prompt, files)

    response = httpx.post(
        f"{base_url.rstrip('/')}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": user_message}],
            "stream": False,
        },
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

    Args:
        coworker: dict with keys 'name', 'model_provider', 'model_name'
        run_dir: Path to the timestamped run directory
        ollama_base_url: Ollama server URL (only used if provider is 'ollama')

    Returns:
        Path to the output result.md file

    Raises:
        ValueError: if prompt or inputs are missing
        anthropic.APIError: if Claude API call fails
        httpx.HTTPError: if Ollama API call fails
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

    # Route to the right provider
    if provider == "claude":
        response_text = _call_claude(model, prompt, files)
    elif provider == "ollama":
        response_text = _call_ollama(model, prompt, files, ollama_base_url)
    else:
        raise ValueError(f"Unknown provider: {provider}")

    # Derive the coworker's top-level outputs dir from run_dir
    # run_dir is: coworkers/<name>/runs/<timestamp>
    coworker_outputs_dir = run_dir.parent.parent / "outputs"

    output_file = _write_result(
        run_dir, name, provider, model, files, response_text, coworker_outputs_dir,
    )
    return output_file
