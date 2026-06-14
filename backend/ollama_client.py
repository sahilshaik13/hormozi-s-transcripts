"""Ollama Cloud client for chat."""

from __future__ import annotations

import time

from backend.config import (
    get_ollama_api_key,
    get_ollama_chat_model,
    get_ollama_host,
)

try:
    from ollama import Client
except ImportError:
    Client = None  # type: ignore[misc, assignment]

RETRY_MAX = 6
RETRY_BASE_DELAY = 5


def _chat_client() -> Client:
    if Client is None:
        raise RuntimeError("ollama package not installed. Run: pip install ollama")
    return Client(
        host=get_ollama_host(),
        headers={"Authorization": f"Bearer {get_ollama_api_key()}"},
    )


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many" in msg


def _normalize_role(role: str) -> str:
    if role in ("model", "assistant"):
        return "assistant"
    if role == "system":
        return "system"
    return "user"


def chat(
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.4,
    num_predict: int = 8192,
) -> tuple[str, str | None]:
    """Return assistant text and Ollama done_reason (e.g. stop, length)."""
    client = _chat_client()
    model = get_ollama_chat_model()

    ollama_messages: list[dict[str, str]] = []
    if system:
        ollama_messages.append({"role": "system", "content": system})
    for msg in messages:
        ollama_messages.append(
            {"role": _normalize_role(msg["role"]), "content": msg["content"]}
        )

    for attempt in range(RETRY_MAX + 1):
        try:
            response = client.chat(
                model=model,
                messages=ollama_messages,
                options={"temperature": temperature, "num_predict": num_predict},
            )
            message = response.get("message") or {}
            content = message.get("content") or ""
            return content, response.get("done_reason")
        except Exception as exc:
            if not is_rate_limit_error(exc) or attempt == RETRY_MAX:
                raise
            time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

    raise RuntimeError("unreachable")


def chat_with_continuations(
    messages: list[dict[str, str]],
    *,
    system: str | None = None,
    temperature: float = 0.4,
    num_predict: int = 8192,
    max_continuations: int = 2,
) -> str:
    """Chat with automatic continuation when output hits num_predict."""
    working_messages = list(messages)
    chunks: list[str] = []
    reason: str | None = None

    for attempt in range(max_continuations + 1):
        text, reason = chat(
            working_messages,
            system=system,
            temperature=temperature,
            num_predict=num_predict,
        )
        if text:
            chunks.append(text)

        if reason != "length":
            break
        if attempt < max_continuations:
            working_messages.append({"role": "assistant", "content": text})
            working_messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue exactly where you stopped. Do not repeat anything "
                        "already said. Finish the complete answer. Do not add a sources block."
                    ),
                }
            )

    answer = "".join(chunks)
    if reason == "length":
        answer += "\n\n_(Response hit token limit — ask a follow-up to continue.)_"
    return answer
