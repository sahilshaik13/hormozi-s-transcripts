"""Shared Hormozi Brain RAG engine — used by terminal chat, MCP, and web API."""

from __future__ import annotations

import json
import re

from backend.embeddings import embed_query
from backend.ollama_client import chat_with_continuations
from backend.paths import VAULT_DIR
from backend.runtime import get_writable_index_dir

try:
    import chromadb
except ImportError as exc:
    raise SystemExit("Run: pip install chromadb") from exc

TOP_K = 8
MIN_RELEVANCE = 0.35
HISTORY_TURNS = 6

DOMAIN_TYPE_MAP = {
    "sales": ["framework", "tactic", "mental-model"],
    "mindset": ["mindset", "mental-model"],
    "hiring": ["framework", "tactic"],
    "offers": ["framework", "tactic"],
    "pricing": ["framework", "tactic"],
    "marketing": ["framework", "tactic", "mental-model"],
    "operations": ["tactic", "framework"],
    "identity": ["mindset", "mental-model"],
    "money": ["framework", "mental-model", "tactic"],
    "scaling": ["framework", "tactic"],
    "leadership": ["mindset", "tactic", "framework"],
    "persuasion": ["tactic", "framework", "mental-model"],
    "content": ["tactic", "framework"],
    "learning": ["mindset", "mental-model"],
}

HORMOZI_SYSTEM = """
You are Alex Hormozi — entrepreneur, investor, and author of $100M Offers and
$100M Leads. You have built and sold multiple businesses and your current portfolio
does over $200M/year in revenue.

You are answering a question from someone who works with you.
They trust your judgment completely. They want your real opinion, not a safe answer.

YOUR COMMUNICATION STYLE:
- Direct. No fluff. No hedging.
- You think in numbered lists when explaining a process.
- You use analogies and stories to make abstract things concrete.
- You are brutally honest. You call out bad thinking.
- You never say "it depends" without immediately telling them what it depends on
  and what to do in each case.
- You speak in the first person. You own your opinions.
- Short sentences. Active voice. High signal per word.
- Never repeat the same paragraph or opening twice in one response.
- When context has a numbered checklist or multi-step process, include EVERY step.
  Do not stop after step 1. Complete the full answer.

YOUR KNOWLEDGE BASE:
You have been given a set of RETRIEVED CONTEXT CHUNKS from your own extracted
knowledge vault. These are notes built from your actual YouTube transcripts.

RULES — follow these exactly:
1. Answer ONLY using the retrieved context provided. Do not invent frameworks,
   statistics, or advice not present in the context.
2. If the context does not contain enough information to answer well, say:
   "I don't have enough in my notes on that specific question. Here's the closest
   I can give you:" — then answer from whatever partial context exists.
3. Do NOT add a sources, citations, or bibliography block at the end. The app shows
   sources separately. End your answer after the final point — no --- dividers.
4. Use clean markdown only: **bold** for emphasis, numbered lists (1. 2. 3.), and
   short paragraphs. No broken link syntax like [Title] (type).
5. If the question has a domain prefix like [sales] or [mindset], focus your answer
   on that domain even if broader context was retrieved.
6. Never break character. You are always Hormozi.
"""


def parse_domain_filter(question: str) -> tuple[str, str | None]:
    """'[sales] how do I close?' → ('how do I close?', 'sales')"""
    match = re.match(r"^\[(\w+)\]\s*(.+)", question.strip(), re.IGNORECASE)
    if match:
        return match.group(2).strip(), match.group(1).lower()
    return question.strip(), None


def retrieve_chunks(
    collection,
    query_vector: list[float],
    top_k: int = TOP_K,
    domain_filter: str | None = None,
) -> list[dict]:
    where = None
    if domain_filter:
        types_for_domain = DOMAIN_TYPE_MAP.get(domain_filter)
        if types_for_domain and len(types_for_domain) == 1:
            where = {"note_type": {"$eq": types_for_domain[0]}}
        elif types_for_domain:
            where = {"note_type": {"$in": types_for_domain}}

    query_kwargs = {
        "query_embeddings": [query_vector],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_kwargs["where"] = where

    results = collection.query(**query_kwargs)
    chunks = []
    for doc, meta, dist in zip(
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    ):
        if dist <= (1 - MIN_RELEVANCE):
            chunks.append({
                "text": doc,
                "note_title": meta.get("note_title", "Unknown"),
                "note_type": meta.get("note_type", "note"),
                "note_path": meta.get("note_path", ""),
                "source_videos": json.loads(meta.get("source_videos", "[]")),
                "distance": dist,
                "relevance": round(1 - dist, 3),
            })
    return chunks


_SOURCE_VIDEO_RE = re.compile(r"\[\[07 Source Notes/([^\]|]+)")


def resolve_source_videos(chunk: dict) -> list[str]:
    videos = list(chunk.get("source_videos") or [])
    if videos:
        return videos

    text = chunk.get("text", "")
    found = _SOURCE_VIDEO_RE.findall(text)
    if found:
        return list(dict.fromkeys(v.strip() for v in found if v.strip()))

    path = (chunk.get("note_path") or "").replace("\\", "/")
    if path.startswith("07 Source Notes/"):
        stem = path.rsplit("/", 1)[-1].removesuffix(".md")
        if stem:
            return [stem]
    return []


def enrich_chunk(chunk: dict) -> dict:
    videos = resolve_source_videos(chunk)
    primary = videos[0] if videos else ""
    return {
        **chunk,
        "source_videos": videos,
        "source_label": primary or chunk.get("note_title", "Vault note"),
    }


_CITATIONS_BLOCK_RE = re.compile(
    r"\n?---\s*\n📎\s*Sources used:[\s\S]*?(?:---\s*)?$",
    re.IGNORECASE,
)


def format_answer(text: str) -> str:
    """Remove LLM citation blocks and trailing horizontal rules."""
    cleaned = _CITATIONS_BLOCK_RE.sub("", text).strip()
    cleaned = re.sub(r"\n---\s*$", "", cleaned).strip()
    cleaned = re.sub(
        r"\n?📎\s*Sources used:[\s\S]*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned


def build_context_block(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant context found in the knowledge base."

    lines = ["RETRIEVED CONTEXT FROM HORMOZI BRAIN VAULT:\n"]
    for i, chunk in enumerate(chunks, 1):
        videos = ", ".join(resolve_source_videos(chunk)) or "Vault note"
        lines.append(f"--- CHUNK {i} ---")
        lines.append(f"Note: {chunk['note_title']}")
        lines.append(f"Type: {chunk['note_type']}")
        lines.append(f"Source video(s): {videos}")
        lines.append(f"Relevance: {chunk['relevance']}")
        lines.append(f"\n{chunk['text']}\n")
    return "\n".join(lines)


def format_chunks_for_display(chunks: list[dict]) -> str:
    if not chunks:
        return "No relevant context found. Try rephrasing or removing the domain filter."

    lines = [f"Found {len(chunks)} relevant chunks:\n"]
    for i, chunk in enumerate(chunks, 1):
        videos = ", ".join(resolve_source_videos(chunk)) or "Vault note"
        lines.append(f"### Chunk {i} — {chunk['note_title']} ({chunk['note_type']})")
        lines.append(f"Relevance: {chunk['relevance']} | Source: {videos}")
        lines.append(chunk["text"])
        lines.append("")
    return "\n".join(lines)


def build_messages(
    history: list[dict],
    context_block: str,
    question: str,
) -> list[dict]:
    messages = []
    for turn in history[-HISTORY_TURNS:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    user_content = f"""CONTEXT FROM MY KNOWLEDGE VAULT:
{context_block}

MY QUESTION:
{question}"""
    messages.append({"role": "user", "content": user_content})
    return messages


def call_hormozi(messages: list[dict]) -> str:
    return chat_with_continuations(
        messages,
        system=HORMOZI_SYSTEM,
        temperature=0.4,
        num_predict=8192,
        max_continuations=2,
    )


class HormoziBrain:
    """Lazy-loaded brain engine — ChromaDB index + Ollama Cloud."""

    def __init__(self) -> None:
        self._collection = None
        self._chunk_count: int | None = None
        self._note_count: int | None = None

    def _load(self) -> None:
        if self._collection is not None:
            return

        index_dir = get_writable_index_dir()
        if not index_dir.exists():
            raise FileNotFoundError(
                f"Index not found at '{index_dir}'. Run tools/build_index.py first."
            )

        chroma = chromadb.PersistentClient(path=str(index_dir))
        try:
            self._collection = chroma.get_collection("hormozi_brain")
            self._chunk_count = self._collection.count()
        except Exception as exc:
            raise RuntimeError(
                "Collection 'hormozi_brain' not found. Run tools/build_index.py first."
            ) from exc

        if VAULT_DIR.exists():
            self._note_count = len(list(VAULT_DIR.rglob("*.md")))
        else:
            self._note_count = 0

    @property
    def collection(self):
        self._load()
        assert self._collection is not None
        return self._collection

    def stats(self) -> dict:
        self._load()
        index_dir = get_writable_index_dir()
        return {
            "vault_dir": str(VAULT_DIR),
            "index_dir": str(index_dir),
            "chunk_count": self._chunk_count,
            "note_count": self._note_count,
            "domains": sorted(DOMAIN_TYPE_MAP.keys()),
        }

    def search(
        self,
        query: str,
        domain: str | None = None,
        top_k: int = TOP_K,
    ) -> list[dict]:
        self._load()
        q, parsed_domain = parse_domain_filter(query)
        domain = domain or parsed_domain
        vector = embed_query(q)
        return retrieve_chunks(self.collection, vector, top_k=top_k, domain_filter=domain)

    def ask(
        self,
        question: str,
        domain: str | None = None,
        history: list[dict] | None = None,
        top_k: int = TOP_K,
    ) -> dict:
        self._load()
        q, parsed_domain = parse_domain_filter(question)
        domain = domain or parsed_domain
        chunks = self.search(q, domain=domain, top_k=top_k)
        if not chunks:
            return {
                "answer": (
                    "No relevant context found in the Hormozi brain for that question. "
                    "Try rephrasing or removing the domain filter."
                ),
                "chunks": [],
                "question": q,
                "domain": domain,
            }

        enriched = [enrich_chunk(c) for c in chunks]
        context_block = build_context_block(enriched)
        messages = build_messages(history or [], context_block, q)
        answer = format_answer(call_hormozi(messages))
        return {
            "answer": answer,
            "chunks": enriched,
            "question": q,
            "domain": domain,
        }


_brain: HormoziBrain | None = None


def get_brain() -> HormoziBrain:
    global _brain
    if _brain is None:
        _brain = HormoziBrain()
    return _brain
