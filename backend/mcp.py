"""
Hormozi Brain MCP Server

Run:
  python -m backend.mcp

Tools:
  - search_hormozi_brain  → retrieve relevant vault chunks
  - ask_hormozi_brain     → full Hormozi-voice answer via Gemini
  - hormozi_brain_stats   → vault / index metadata
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from backend.core import DOMAIN_TYPE_MAP, format_chunks_for_display, get_brain

mcp = FastMCP(
    "Hormozi Brain",
    instructions=(
        "Personal Alex Hormozi knowledge vault (YouTube transcripts → RAG index). "
        "Use search_hormozi_brain to pull grounded context into your reply, or "
        "ask_hormozi_brain for a pre-synthesized Hormozi-voice answer. "
        "Not affiliated with Alex Hormozi or Acquisition.com."
    ),
)


@mcp.tool()
def search_hormozi_brain(
    query: str,
    domain: str | None = None,
    top_k: int = 8,
) -> str:
    """
    Search the Hormozi brain vault and return relevant note chunks with citations.

    Args:
        query: Question or topic to search for.
        domain: Optional filter — sales, mindset, hiring, offers, pricing, etc.
        top_k: Number of chunks to retrieve (default 8, max 20).
    """
    top_k = max(1, min(int(top_k), 20))
    domain = domain.lower().strip() if domain else None
    if domain and domain not in DOMAIN_TYPE_MAP:
        return (
            f"Unknown domain '{domain}'. Valid: "
            + ", ".join(sorted(DOMAIN_TYPE_MAP.keys()))
        )

    try:
        chunks = get_brain().search(query, domain=domain, top_k=top_k)
        return format_chunks_for_display(chunks)
    except Exception as exc:
        return f"Search error: {exc}"


@mcp.tool()
def ask_hormozi_brain(
    question: str,
    domain: str | None = None,
) -> str:
    """
    Ask a question and get a full answer in Alex Hormozi's voice (Gemini + RAG).

    Args:
        question: Your business question.
        domain: Optional domain filter (same values as search_hormozi_brain).
    """
    domain = domain.lower().strip() if domain else None
    if domain and domain not in DOMAIN_TYPE_MAP:
        return (
            f"Unknown domain '{domain}'. Valid: "
            + ", ".join(sorted(DOMAIN_TYPE_MAP.keys()))
        )

    try:
        result = get_brain().ask(question, domain=domain)
        chunks = result["chunks"]
        if not chunks:
            return result["answer"]

        seen: list[str] = []
        for chunk in chunks:
            title = chunk["note_title"]
            if title not in seen:
                seen.append(title)

        footer = f"\n\n---\nNodes accessed ({len(seen)}): {', '.join(seen)}"
        return result["answer"] + footer
    except Exception as exc:
        return f"Ask error: {exc}"


@mcp.tool()
def hormozi_brain_stats() -> str:
    """Return vault and index statistics (note count, chunk count, available domains)."""
    try:
        s = get_brain().stats()
        domains = ", ".join(s["domains"])
        return (
            f"Hormozi Brain stats:\n"
            f"  Vault notes : {s['note_count']}\n"
            f"  Index chunks: {s['chunk_count']}\n"
            f"  Vault path  : {s['vault_dir']}\n"
            f"  Index path  : {s['index_dir']}\n"
            f"  Domains     : {domains}"
        )
    except Exception as exc:
        return f"Stats error: {exc}"


if __name__ == "__main__":
    mcp.run()
