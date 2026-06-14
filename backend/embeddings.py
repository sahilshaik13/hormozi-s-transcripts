"""Text embeddings for RAG — FastEmbed (default) or local Ollama."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from backend.config import (
    get_embed_backend,
    get_ollama_embed_api_key,
    get_ollama_embed_host,
    get_ollama_embed_model,
    load_env,
)

RETRY_MAX = 6
RETRY_BASE_DELAY = 5
EMBED_BATCH_MAX = 32
EMBED_DELAY = 0.25

_fastembed_model = None


def is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many" in msg


def _fastembed():
    global _fastembed_model
    if _fastembed_model is None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise RuntimeError(
                "FastEmbed not installed. Run: pip install fastembed"
            ) from exc
        from backend.config import get_fastembed_model

        _fastembed_model = TextEmbedding(get_fastembed_model())
    return _fastembed_model


def _embed_fastembed(texts: list[str]) -> list[list[float]]:
    model = _fastembed()
    return [vec.tolist() for vec in model.embed(texts)]


def _embed_ollama_batch(batch: list[str]) -> list[list[float]]:
    host = get_ollama_embed_host()
    model = get_ollama_embed_model()
    api_key = get_ollama_embed_api_key()
    inp = batch[0] if len(batch) == 1 else batch

    url = f"{host.rstrip('/')}/api/embed"
    body = json.dumps({"model": model, "input": inp}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 401:
            raise RuntimeError(
                f"Ollama embed 401 at {host}. Use EMBED_BACKEND=fastembed (default), "
                "or run local Ollama: ollama pull nomic-embed-text and set "
                "OLLAMA_EMBED_HOST=http://127.0.0.1:11434"
            ) from exc
        raise RuntimeError(f"Ollama embed HTTP {exc.code}: {detail}") from exc

    embeddings = data.get("embeddings") or []
    if not embeddings:
        raise RuntimeError(f"Ollama embed returned no vectors for model '{model}'")
    return embeddings


def embed_texts(texts: list[str]) -> list[list[float]]:
    load_env()
    if not texts:
        return []

    backend = get_embed_backend()
    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBED_BATCH_MAX):
        batch = texts[start : start + EMBED_BATCH_MAX]

        for attempt in range(RETRY_MAX + 1):
            try:
                if backend == "ollama":
                    vectors = _embed_ollama_batch(batch)
                else:
                    vectors = _embed_fastembed(batch)
                all_vectors.extend(vectors)
                break
            except Exception as exc:
                if not is_rate_limit_error(exc) or attempt == RETRY_MAX:
                    raise
                time.sleep(RETRY_BASE_DELAY * (2 ** attempt))

        if start + EMBED_BATCH_MAX < len(texts):
            time.sleep(EMBED_DELAY)

    return all_vectors


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
