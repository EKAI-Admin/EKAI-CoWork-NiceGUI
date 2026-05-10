from dataclasses import dataclass, field
from datetime import datetime

import httpx


@dataclass
class User:
    id: int = 0
    username: str = ""
    email: str = ""
    password_hash: str = ""
    created_at: str = ""


@dataclass
class CoWorker:
    id: int = 0
    name: str = ""
    job_description: str = ""
    workflow: str = ""
    status: str = "active"
    model_provider: str = "claude"
    model_name: str = "claude-sonnet-4-20250514"
    join_date: str = ""
    created_by: int = 0


@dataclass
class UserSettings:
    id: int = 0
    user_id: int = 0
    default_provider: str = "claude"
    default_model: str = "claude-sonnet-4-20250514"
    ollama_base_url: str = "http://localhost:11434"



CLAUDE_MODELS = [
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "claude-haiku-4-5-20251001",
]

OLLAMA_MODELS_FALLBACK = [
    "llama3",
    "mistral",
    "codellama",
    "phi3",
    "gemma2",
]


def get_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Fetch installed Ollama models from the API. Falls back to hardcoded list."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=5.0)
        resp.raise_for_status()
        models = resp.json().get("models", [])
        return [m["name"] for m in models] if models else OLLAMA_MODELS_FALLBACK
    except Exception:
        return OLLAMA_MODELS_FALLBACK


# For backward compat — will be replaced by dynamic calls
OLLAMA_MODELS = OLLAMA_MODELS_FALLBACK

STATUS_OPTIONS = ["active", "inactive", "paused"]

WORKFLOW_OPTIONS = [
    "Code Review",
    "Documentation",
    "Testing",
    "Deployment",
    "Data Analysis",
    "Customer Support",
    "Content Creation",
    "Security Audit",
    "Performance Monitoring",
    "Bug Triage",
]
