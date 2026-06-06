"""
ASK HORMOZI — Terminal RAG Chat

USAGE:
  python cli/ask.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.core import (
    HISTORY_TURNS,
    TOP_K,
    get_brain,
    parse_domain_filter,
)
from backend.paths import PROJECT_ROOT, VAULT_DIR
from backend.viz import open_retrieval_graph


def print_divider():
    print("\n" + "━" * 60 + "\n")


CASUAL_INPUTS = {
    "hey", "hi", "hello", "yo", "sup", "hiya",
    "thanks", "thank you", "ok", "okay", "cool", "nice",
}


def is_casual_input(text: str) -> bool:
    return text.lower().strip().rstrip("!?.,") in CASUAL_INPUTS


def is_cursor_noise(text: str) -> bool:
    markers = ("[node.js fs]", "DeprecationWarning", "service_worker",
               "EPERM", "storage.json", "FileSystemError", "Dr [Error]")
    return any(m in text for m in markers)


def print_welcome(note_count: int, chunk_count: int):
    print(f"""
╔══════════════════════════════════════════════════════════════╗
║   🧠  ASK HORMOZI — RAG Terminal Chat                       ║
║   Powered by your {note_count}-note Obsidian brain                   ║
╠══════════════════════════════════════════════════════════════╣
║   Commands:                                                  ║
║     exit / quit  → close                                    ║
║     clear        → reset conversation history               ║
║     sources      → show sources from last answer            ║
║     graph        → save graph HTML (refresh Live Server)    ║
║     graph session→ cumulative session graph                 ║
║                                                              ║
║   Domain filter (optional):                                  ║
║     [sales] how do I close a skeptical client?              ║
║     [mindset] I keep self-sabotaging                        ║
║     [hiring] first hire for a solo business                 ║
╠══════════════════════════════════════════════════════════════╣
║   Tip: run scripts/run_ask.bat from project root            ║
╚══════════════════════════════════════════════════════════════╝

  ✓ Index loaded — {chunk_count} chunks ready
""")


def main():
    brain = get_brain()
    stats = brain.stats()
    print_welcome(stats["note_count"] or 0, stats["chunk_count"] or 0)

    history: list[dict] = []
    last_chunks: list[dict] = []
    last_question = ""
    session_chunks: list[dict] = []
    session_hits: dict[str, int] = {}

    while True:
        try:
            print("You: ", end="")
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Closing. Stay hard.")
            break

        if not user_input:
            continue

        if is_cursor_noise(user_input):
            continue

        if is_casual_input(user_input):
            print("\n  Hormozi: What's the actual question? Ask me something specific.\n")
            continue

        if user_input.lower() in ("exit", "quit"):
            print("\n  Closing. Stay hard.")
            break

        if user_input.lower() == "clear":
            history = []
            last_chunks = []
            last_question = ""
            session_chunks = []
            session_hits = {}
            print("  ✓ Conversation history cleared.\n")
            continue

        if user_input.lower() in ("graph", "graph session"):
            scope = "session" if user_input.lower() == "graph session" else "last"
            chunks_for_graph = session_chunks if scope == "session" else last_chunks
            question_for_graph = "" if scope == "session" else last_question

            if not chunks_for_graph:
                print("  No retrieved nodes to visualize yet. Ask a question first.\n")
                continue

            out_name = "brain-session-graph.html" if scope == "session" else "brain-retrieval-graph.html"
            try:
                out = open_retrieval_graph(
                    chunks_for_graph,
                    vault_dir=str(VAULT_DIR),
                    question=question_for_graph,
                    output_path=PROJECT_ROOT / out_name,
                    session_hits=session_hits,
                    open_browser=False,
                )
                unique = len({c.get("note_path") or c.get("note_title") for c in chunks_for_graph})
                print(f"  ✓ Graph saved — {unique} nodes accessed")
                print(f"    Refresh in Live Server, or open:")
                print(f"    {out.resolve()}\n")
            except Exception as e:
                print(f"  ❌ Graph error: {e}\n")
            continue

        if user_input.lower() == "sources":
            if not last_chunks:
                print("  No sources from previous answer.\n")
            else:
                print_divider()
                print("📎 Full source metadata from last answer:\n")
                for i, chunk in enumerate(last_chunks, 1):
                    videos = ", ".join(chunk["source_videos"]) or "Unknown"
                    print(f"  [{i}] {chunk['note_title']}")
                    print(f"      Type      : {chunk['note_type']}")
                    print(f"      Path      : {chunk['note_path']}")
                    print(f"      Videos    : {videos}")
                    print(f"      Relevance : {chunk['relevance']}\n")
                print_divider()
            continue

        if user_input.lower() == "help":
            print("""
  Commands:
    exit / quit  → close the chat
    clear        → reset conversation history
    sources      → show full metadata of last retrieved chunks
    graph        → open Obsidian-style graph of last retrieval
    graph session→ graph of all nodes accessed this session
    help         → this list

  Domain filters (prefix your question):
    [sales]       [mindset]    [hiring]    [offers]
    [pricing]     [marketing]  [scaling]   [operations]
    [identity]    [money]      [leadership][persuasion]
    [content]     [learning]
""")
            continue

        question, domain = parse_domain_filter(user_input)
        if domain:
            print(f"  🔍 Filtering by domain: [{domain}]\n")

        print("  ⟳ Searching brain & thinking...", end="", flush=True)
        try:
            result = brain.ask(question, domain=domain, history=history, top_k=TOP_K)
            answer = result["answer"]
            chunks = result["chunks"]
            last_chunks = chunks
            last_question = question
            session_chunks.extend(chunks)
            for chunk in chunks:
                key = chunk.get("note_path") or chunk.get("note_title", "Unknown")
                session_hits[key] = session_hits.get(key, 0) + 1
            print(f" {len(chunks)} relevant chunks found\n")
        except Exception as e:
            print(f"\n  ❌ Error: {e}\n")
            continue

        if not chunks:
            print(answer + "\n")
            continue

        print_divider()
        print("Hormozi:\n")
        print(answer)
        print_divider()

        seen: list[str] = []
        for chunk in chunks:
            title = chunk["note_title"]
            if title not in seen:
                seen.append(title)
        print(f"  Nodes accessed ({len(seen)}): {', '.join(seen)}")
        print("  💡 Type 'graph' to visualize · 'sources' for full metadata\n")

        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": answer})
        if len(history) > HISTORY_TURNS * 2:
            history = history[-(HISTORY_TURNS * 2):]


if __name__ == "__main__":
    main()
