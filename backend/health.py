"""Health checks for brain, embeddings, and Ollama chat."""

from __future__ import annotations

from backend.config import (
    get_embed_backend,
    get_fastembed_model,
    get_ollama_chat_model,
    get_ollama_embed_model,
    get_ollama_host,
    load_env,
)


def format_brain_stats(data: dict) -> str:
    """Format brain stats dict for MCP / CLI display."""
    lines = ["HORMOZI BRAIN — VAULT STATS\n"]

    notes = data.get("note_count", data.get("total_notes", data.get("notes", "?")))
    chunks = data.get("chunk_count", data.get("total_chunks", data.get("chunks", "?")))
    lines.append(f"  Notes  : {notes}")
    lines.append(f"  Chunks : {chunks}")

    by_type = data.get("by_type", data.get("note_types"))
    if isinstance(by_type, dict) and by_type:
        lines.append("\n  By type:")
        for key, count in by_type.items():
            lines.append(f"    {key:<20} {count}")

    domains = data.get("by_domain", data.get("domains"))
    if isinstance(domains, list) and domains:
        lines.append(f"\n  Domains ({len(domains)}):")
        for domain in domains:
            lines.append(f"    #{domain}")
    elif isinstance(domains, dict) and domains:
        lines.append("\n  By domain:")
        for key, count in domains.items():
            lines.append(f"    #{key:<18} {count}")

    if data.get("vault_dir"):
        lines.append(f"\n  Vault : {data['vault_dir']}")
    if data.get("index_dir"):
        lines.append(f"  Index : {data['index_dir']}")

    return "\n".join(lines)


def check_brain() -> dict:
    load_env()
    try:
        from backend.core import get_brain

        stats = get_brain().stats()
        chunks = stats.get("chunk_count") or 0
        status = "ok" if chunks > 0 else "degraded"
        return {"status": status, **stats}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def check_embeddings() -> dict:
    load_env()
    backend = get_embed_backend()
    try:
        from backend.embeddings import embed_query

        vector = embed_query("health check")
        info: dict = {
            "status": "ok",
            "backend": backend,
            "dimensions": len(vector),
        }
        if backend == "fastembed":
            info["model"] = get_fastembed_model()
        else:
            info["model"] = get_ollama_embed_model()
        return info
    except Exception as exc:
        return {
            "status": "error",
            "backend": backend,
            "error": str(exc),
        }


def check_ai(*, probe: bool = True) -> dict:
    load_env()
    model = get_ollama_chat_model()
    host = get_ollama_host()
    base = {"model": model, "host": host}

    if not probe:
        return {**base, "status": "skipped", "message": "AI probe disabled"}

    try:
        from backend.ollama_client import chat

        content, reason = chat(
            messages=[{"role": "user", "content": "Reply with exactly: ok"}],
            num_predict=32,
            temperature=0,
        )
        return {
            **base,
            "status": "ok",
            "done_reason": reason,
            "probe_reply": (content or "").strip()[:120],
        }
    except Exception as exc:
        return {**base, "status": "error", "error": str(exc)}


def collect_health(*, probe_ai: bool = True) -> dict:
    brain = check_brain()
    embeddings = check_embeddings()
    ai = check_ai(probe=probe_ai)

    checks = {"brain": brain, "embeddings": embeddings, "ai": ai}
    statuses = [c.get("status") for c in checks.values()]

    if "error" in statuses:
        overall = "error"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    return {"status": overall, "version": "2.0.0", "checks": checks}


def format_health_report(data: dict) -> str:
    lines = [
        f"HORMOZI BRAIN HEALTH — {data.get('status', '?').upper()}",
        f"  version: {data.get('version', '?')}\n",
    ]

    for name, check in data.get("checks", {}).items():
        status = check.get("status", "?")
        lines.append(f"  [{status.upper():^7}] {name}")

        if name == "brain":
            if check.get("note_count") is not None:
                lines.append(
                    f"           notes={check.get('note_count')} "
                    f"chunks={check.get('chunk_count')}"
                )
            if check.get("error"):
                lines.append(f"           error: {check['error']}")

        elif name == "embeddings":
            if check.get("backend"):
                lines.append(
                    f"           backend={check['backend']} "
                    f"model={check.get('model', '?')} "
                    f"dims={check.get('dimensions', '?')}"
                )
            if check.get("error"):
                lines.append(f"           error: {check['error']}")

        elif name == "ai":
            if check.get("model"):
                lines.append(f"           model={check['model']}")
            if check.get("probe_reply"):
                lines.append(f"           probe: {check['probe_reply'][:80]}")
            if check.get("error"):
                lines.append(f"           error: {check['error']}")
            if check.get("message"):
                lines.append(f"           {check['message']}")

        lines.append("")

    return "\n".join(lines).rstrip()
