"""
HORMOZI BRAIN — Index Builder

USAGE:
  python tools/build_index.py
  python tools/build_index.py --rebuild   # non-interactive full rebuild
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

# Project root must be on sys.path before `import tools.*` or `import backend.*`
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.embeddings import embed_texts, is_rate_limit_error
from backend.paths import INDEX_DIR, VAULT_DIR

try:
    import chromadb
except ImportError:
    print("❌  Run: pip install chromadb")
    exit(1)

CHUNK_SIZE = 500
CHUNK_OVERLAP = 50
DELAY_EMBED = 1.0
BATCH_EMBED_SIZE = 50
RETRY_MAX = 8
RETRY_BASE_DELAY = 5
EMBED_BATCH_MAX = 100


def parse_frontmatter(text: str) -> tuple[dict, str]:
    meta = {}
    body = text

    if text.startswith("---"):
        end = text.find("---", 3)
        if end != -1:
            fm_block = text[3:end].strip()
            body = text[end + 3:].strip()
            for line in fm_block.splitlines():
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip().strip('"')
    return meta, body


def chunk_text(text: str, chunk_size_chars: int = 2000, overlap: int = 200) -> list[str]:
    if len(text) <= chunk_size_chars:
        return [text.strip()] if text.strip() else []

    chunks = []
    paragraphs = re.split(r"\n\n+", text)
    current = ""

    for para in paragraphs:
        if len(current) + len(para) <= chunk_size_chars:
            current += "\n\n" + para
        else:
            if current.strip():
                chunks.append(current.strip())
            overlap_text = current[-overlap:] if len(current) > overlap else current
            current = overlap_text + "\n\n" + para

    if current.strip():
        chunks.append(current.strip())

    return chunks


def get_folder_type(path: Path, vault_dir: Path) -> str:
    relative = path.relative_to(vault_dir)
    parts = relative.parts
    if len(parts) > 1:
        folder = parts[0]
        mapping = {
            "00 MOCs": "moc",
            "01 Frameworks": "framework",
            "02 Mental Models": "mental-model",
            "03 Tactics": "tactic",
            "04 Mindset Principles": "mindset",
            "05 Stories & Analogies": "story",
            "06 Quotes": "quotes",
            "07 Source Notes": "source-note",
        }
        return mapping.get(folder, "note")
    return "index"


def extract_source_videos(body: str) -> list[str]:
    pattern = r"\[\[07 Source Notes/([^\]|]+)"
    matches = [m.strip() for m in re.findall(pattern, body) if m.strip()]
    if matches:
        return list(dict.fromkeys(matches))
    appears = re.findall(r"^\s*-\s+\[\[07 Source Notes/([^\]|]+)", body, re.MULTILINE)
    return list(dict.fromkeys(m.strip() for m in appears if m.strip()))


def is_rate_limit_error_local(exc: Exception) -> bool:
    return is_rate_limit_error(exc)


def _embed_batch(batch: list[str]) -> list[list[float]]:
    for attempt in range(RETRY_MAX + 1):
        try:
            return embed_texts(batch)
        except Exception as exc:
            if not is_rate_limit_error_local(exc) or attempt == RETRY_MAX:
                raise
            wait = RETRY_BASE_DELAY * (2 ** attempt)
            print(f"  ⏳ Rate limited — waiting {wait}s (retry {attempt + 1}/{RETRY_MAX})...")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def embed_texts_for_index(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []

    all_vectors: list[list[float]] = []

    for start in range(0, len(texts), EMBED_BATCH_MAX):
        batch = texts[start:start + EMBED_BATCH_MAX]
        all_vectors.extend(_embed_batch(batch))
        if start + EMBED_BATCH_MAX < len(texts):
            time.sleep(DELAY_EMBED)

    return all_vectors


def main():
    parser = argparse.ArgumentParser(description="Build Hormozi Brain ChromaDB index")
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="Delete existing index and rebuild from scratch (non-interactive)",
    )
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════════╗
║         HORMOZI BRAIN — Index Builder                       ║
║         Embeddings: FastEmbed (local, no API key)           ║
╚══════════════════════════════════════════════════════════════╝
""")

    vault_path = Path(VAULT_DIR)
    if not vault_path.exists():
        print(f"❌  Vault not found at '{VAULT_DIR}'")
        exit(1)

    all_notes = list(vault_path.rglob("*.md"))
    total_notes = len(all_notes)
    print(f"  📁 Vault: {vault_path.resolve()}")
    print(f"  📝 Notes found: {total_notes}")

    print(f"  💾 Index location: {Path(INDEX_DIR).resolve()}\n")
    chroma_client = chromadb.PersistentClient(path=str(INDEX_DIR))

    existing = [c.name for c in chroma_client.list_collections()]
    resume_mode = False
    existing_ids: set[str] = set()

    if "hormozi_brain" in existing:
        collection = chroma_client.get_collection("hormozi_brain")
        existing_count = collection.count()
        if args.rebuild:
            choice = "y"
            print(f"  ⚠  Existing index found with {existing_count} chunks.")
            print("  --rebuild: deleting and rebuilding from scratch.\n")
        else:
            print(f"  ⚠  Existing index found with {existing_count} chunks.")
            print("  Options: (r)esume missing  (y) rebuild from scratch  (n) use existing")
            choice = input("  Choice [r/y/n]: ").strip().lower()
        if choice == "y":
            chroma_client.delete_collection("hormozi_brain")
            collection = chroma_client.create_collection(
                name="hormozi_brain",
                metadata={"hnsw:space": "cosine"},
            )
            print("  🗑  Old index deleted.\n")
        elif choice == "r":
            resume_mode = True
            if existing_count:
                stored = collection.get(include=[])
                existing_ids = set(stored["ids"])
            print(f"  ↻ Resuming — will skip {len(existing_ids)} existing chunks.\n")
        else:
            print("  ✓ Using existing index. Run cli/ask.py to query.")
            return
    else:
        collection = chroma_client.create_collection(
            name="hormozi_brain",
            metadata={"hnsw:space": "cosine"},
        )

    print(f"  ⟳ Processing and embedding {total_notes} notes...\n")

    total_chunks = 0
    skipped = 0
    resumed = 0
    errors = []

    for i, note_path in enumerate(all_notes, 1):
        try:
            raw = note_path.read_text(encoding="utf-8")
            if not raw.strip():
                skipped += 1
                continue

            meta, body = parse_frontmatter(raw)
            note_title = meta.get("title", note_path.stem)
            note_type = meta.get("type", get_folder_type(note_path, vault_path))
            note_tags = meta.get("tags", "")
            source_videos = extract_source_videos(body)

            clean_body = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]",
                                 lambda m: m.group(2) or m.group(1), body)
            clean_body = re.sub(r"^#+\s*", "", clean_body, flags=re.MULTILINE)
            clean_body = clean_body.strip()

            if not clean_body:
                skipped += 1
                continue

            chunks = chunk_text(clean_body)
            if not chunks:
                skipped += 1
                continue

            context_prefix = f"Note: {note_title}\nType: {note_type}\nTags: {note_tags}\n\n"

            pending = []
            for chunk_idx, chunk in enumerate(chunks):
                chunk_id = f"{note_path.stem}__chunk{chunk_idx}"
                if resume_mode and chunk_id in existing_ids:
                    resumed += 1
                    continue
                pending.append({
                    "id": chunk_id,
                    "chunk": chunk,
                    "embed_input": context_prefix + chunk,
                    "chunk_idx": chunk_idx,
                })

            if not pending:
                continue

            vectors = embed_texts_for_index(
                [item["embed_input"] for item in pending],
            )

            collection.add(
                ids=[item["id"] for item in pending],
                embeddings=vectors,
                documents=[item["chunk"] for item in pending],
                metadatas=[{
                    "note_title": note_title,
                    "note_type": note_type,
                    "note_path": str(note_path.relative_to(vault_path)).replace("\\", "/"),
                    "note_tags": note_tags,
                    "source_videos": json.dumps(source_videos),
                    "chunk_index": item["chunk_idx"],
                    "total_chunks": len(chunks),
                } for item in pending],
            )
            total_chunks += len(pending)
            time.sleep(DELAY_EMBED)

            if i % BATCH_EMBED_SIZE == 0 or i == total_notes:
                print(f"  [{i:03d}/{total_notes}] ✓  {total_chunks} new chunks indexed")

        except Exception as e:
            errors.append((note_path.name, str(e)))
            print(f"  ✗ Error on {note_path.name}: {e}")

    print(f"\n{'═'*60}")
    print("  ✅  INDEX BUILT")
    print(f"  📊 Notes processed : {total_notes - skipped - len(errors)}")
    print(f"  📦 New chunks      : {total_chunks}")
    if resumed:
        print(f"  ↻  Skipped (exist) : {resumed}")
    print(f"  ⏭  Skipped (empty) : {skipped}")
    print(f"  ✗  Errors          : {len(errors)}")
    print(f"  💾 Saved to        : {Path(INDEX_DIR).resolve()}")
    print(f"{'═'*60}")

    if errors:
        print("\n  ⚠  Errors:")
        for name, err in errors:
            print(f"    - {name}: {err}")

    print("\n  ✓ Run cli/ask.py to start querying.\n")


if __name__ == "__main__":
    main()
