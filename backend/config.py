"""Load secrets from .env — never commit .env to git."""

from __future__ import annotations

import os

from backend.paths import PROJECT_ROOT


def load_env() -> None:
    """Load .env from project root into os.environ (does not override existing)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
        load_dotenv(env_path, override=False)
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
        os.environ.setdefault(key, value)


def get_gemini_api_key() -> str:
    load_env()
    key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key or key in ("your_key_here", "YOUR_GEMINI_API_KEY_HERE"):
        raise RuntimeError(
            "GEMINI_API_KEY not set. Add it in Vercel → Settings → Environment Variables."
        )
    return key
