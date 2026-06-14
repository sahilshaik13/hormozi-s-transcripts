"""Load secrets from .env — never commit .env to git."""

from __future__ import annotations

import os

from backend.paths import PROJECT_ROOT

DEFAULT_OLLAMA_HOST = "https://ollama.com"
DEFAULT_OLLAMA_CHAT_MODEL = "deepseek-v4-flash:cloud"
DEFAULT_OLLAMA_EMBED_MODEL = "nomic-embed-text"
DEFAULT_FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
DEFAULT_EMBED_BACKEND = "fastembed"


def load_env() -> None:
    """Load .env from project root (always wins over empty shell vars)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=True)
        return
    except ImportError:
        pass

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def get_ollama_api_key() -> str:
    load_env()
    key = os.getenv("OLLAMA_API_KEY", "").strip()
    if not key or key in ("your_key_here", "YOUR_OLLAMA_API_KEY_HERE"):
        raise RuntimeError(
            "OLLAMA_API_KEY not set. Add it in .env or Render → Environment Variables."
        )
    return key


def get_ollama_host() -> str:
    load_env()
    host = os.getenv("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).strip().rstrip("/")
    return host or DEFAULT_OLLAMA_HOST


def get_ollama_embed_host() -> str:
    load_env()
    host = os.getenv("OLLAMA_EMBED_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    return host or "http://127.0.0.1:11434"


def _is_local_host(host: str) -> bool:
    lower = host.lower()
    return lower.startswith("http://127.0.0.1") or lower.startswith("http://localhost")


def get_ollama_embed_api_key() -> str | None:
    if _is_local_host(get_ollama_embed_host()):
        return None
    return get_ollama_api_key()


def get_ollama_chat_model() -> str:
    load_env()
    model = os.getenv("OLLAMA_CHAT_MODEL", DEFAULT_OLLAMA_CHAT_MODEL).strip()
    return model or DEFAULT_OLLAMA_CHAT_MODEL


def get_ollama_embed_model() -> str:
    load_env()
    model = os.getenv("OLLAMA_EMBED_MODEL", DEFAULT_OLLAMA_EMBED_MODEL).strip()
    return model or DEFAULT_OLLAMA_EMBED_MODEL


def get_embed_backend() -> str:
    load_env()
    backend = os.getenv("EMBED_BACKEND", DEFAULT_EMBED_BACKEND).strip().lower()
    if backend not in ("fastembed", "ollama"):
        raise RuntimeError(
            f"Invalid EMBED_BACKEND '{backend}'. Use 'fastembed' or 'ollama'."
        )
    return backend


def get_fastembed_model() -> str:
    load_env()
    model = os.getenv("FASTEMBED_MODEL", DEFAULT_FASTEMBED_MODEL).strip()
    return model or DEFAULT_FASTEMBED_MODEL
