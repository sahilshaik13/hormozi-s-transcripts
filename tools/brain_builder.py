"""
╔══════════════════════════════════════════════════════════════════════╗
║        HORMOZI BRAIN BUILDER v2 — Obsidian Vault Generator          ║
║        Model: deepseek-v4-flash:cloud via Ollama Cloud              ║
║        Fix: Robust JSON repair + half-batch retry in Phase 2        ║
╚══════════════════════════════════════════════════════════════════════╝

CHANGES FROM v1:
  - repair_json()         — fixes common LLM JSON malformation issues
  - Half-batch retry      — failed batches split in half and retried
  - Partial merge         — vault assembles from whatever batches succeeded
  - Raw fallback cache    — saves raw text on total failure for inspection
  - Phase 1 fully cached  — zero re-extraction calls if cache exists

USAGE:
  python tools/brain_builder.py
  Set OLLAMA_API_KEY in .env (see .env.example)
"""

# ════════════════════════════════════════════════════════════════
#  CONFIG — edit only this block
# ════════════════════════════════════════════════════════════════

# Paths from backend.paths (project root)
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.paths import CACHE_DIR, TRANSCRIPTS_DIR, VAULT_DIR as OUTPUT_DIR

DELAY_BETWEEN_CALLS = 4
MAX_RETRIES         = 3
SYNTHESIS_BATCH     = 30      # initial batch size
SYNTHESIS_HALF      = 15      # retry batch size on failure

# ════════════════════════════════════════════════════════════════
#  IMPORTS
# ════════════════════════════════════════════════════════════════

import json
import time
import re
import hashlib
from pathlib import Path
from datetime import datetime

from backend.ollama_client import chat as ollama_chat

# ════════════════════════════════════════════════════════════════
#  PROMPTS  (unchanged from v1)
# ════════════════════════════════════════════════════════════════

EXTRACTION_SYSTEM = """
You are a precision knowledge extraction engine. Your sole function is to extract
discrete, atomic, reusable knowledge nodes from a YouTube transcript.

YOU DO NOT SUMMARIZE. You EXTRACT.

A summary collapses information. An extraction preserves the original insight in its
most portable, reusable form — stripped of filler, kept structurally intact.

EXTRACTION LENSES — analyze through all four simultaneously:

1. STRATEGIST LENS
   Look for: named frameworks, decision-making models, business logic systems,
   pricing/offer structures, market positioning ideas, growth levers.

2. PSYCHOLOGIST LENS
   Look for: identity-level beliefs ("I am the kind of person who..."),
   reframes of common fears, motivation structures, emotional drivers behind
   business decisions, self-talk patterns, mindset shifts.

3. OPERATOR LENS
   Look for: specific tactical moves ("first do X, then Y"), hiring/firing rules,
   process templates, scripts, SOPs described verbally, metrics and thresholds
   mentioned, specific numbers or ratios.

4. STORYTELLER LENS
   Look for: analogies used to explain a concept, parables or stories told,
   metaphors that crystallize an idea, vivid examples with characters or scenes.

OUTPUT FORMAT — return ONLY valid JSON, nothing else, no markdown fences:

{
  "video_title": "string — extract from content or filename",
  "core_idea": "string — the single most important insight from this video in one sentence",
  "domains": ["array", "of", "tags"],
  "mental_models": [
    {
      "name": "short name for the model",
      "description": "what it is",
      "application": "how to use it",
      "quote": "verbatim phrase from transcript that captures it, if any"
    }
  ],
  "frameworks": [
    {
      "name": "framework name",
      "steps": ["step 1", "step 2"],
      "purpose": "what problem it solves",
      "quote": "verbatim phrase, if any"
    }
  ],
  "tactics": [
    {
      "action": "specific executable move",
      "context": "when/why to use it",
      "outcome": "expected result"
    }
  ],
  "mindset_principles": [
    {
      "principle": "the belief or identity statement",
      "reframe": "what most people believe vs what Hormozi believes",
      "quote": "verbatim phrase, if any"
    }
  ],
  "stories_analogies": [
    {
      "title": "short label for this story/analogy",
      "narrative": "the story or analogy summarized in 2-3 sentences",
      "lesson": "what it illustrates",
      "quote": "opening line or key phrase verbatim, if any"
    }
  ],
  "quotes": [
    {
      "text": "exact verbatim quote",
      "context": "what topic this was said about",
      "punchline_type": "one of: provocative / instructional / identity / counterintuitive"
    }
  ],
  "contrarian_takes": [
    {
      "conventional_belief": "what most people think",
      "hormozi_belief": "what he argues instead",
      "reasoning": "his justification"
    }
  ],
  "key_numbers": [
    {
      "metric": "what is being measured",
      "value": "the number or ratio mentioned",
      "context": "what it applies to"
    }
  ]
}

RULES:
- Every field must be populated if evidence exists in the transcript.
- Omit a field only if truly absent — do not fabricate.
- Quotes must be verbatim from the transcript, not paraphrased.
- Names for mental models and frameworks should be crisp (2-4 words max).
- Domains must come from this controlled list:
  sales, offers, pricing, marketing, hiring, operations, mindset, identity,
  productivity, scaling, money, relationships, content, persuasion, leadership,
  investing, health, learning
- Return ONLY the JSON. No preamble. No explanation. No markdown.
"""

EXTRACTION_USER = """
FILENAME: {filename}

TRANSCRIPT:
{transcript}

Extract all knowledge nodes using all four lenses. Return only JSON.
"""

SYNTHESIS_SYSTEM = """
You are a knowledge synthesis engine for an Obsidian second brain.

You receive a collection of extraction JSONs from multiple YouTube video transcripts
by Alex Hormozi. Your job is to:

1. DEDUPLICATE — identify concepts that appear across multiple videos.
   Merge near-identical ideas into one canonical node. Track which videos it appeared in.

2. SCORE FREQUENCY — count how many unique videos each concept appeared in.
   High-frequency concepts (3+ videos) are "core beliefs" — flag them.

3. BUILD CONNECTIONS — identify which frameworks reference which mental models,
   which tactics implement which frameworks, which stories illustrate which principles.
   Express these as [[wikilink]] references.

4. CREATE MOC ENTRIES — for each domain, produce a structured list of all nodes
   that belong to it, sorted by frequency (most repeated first).

5. IDENTIFY HORMOZI'S WORLDVIEW PILLARS — the 5-10 beliefs that underpin EVERYTHING
   he teaches. These will be the root nodes of the brain.

CRITICAL JSON RULES — you MUST follow these exactly:
- Return ONLY valid JSON. No markdown. No backticks. No preamble.
- Every string value must be properly closed with a double quote.
- Every object must be properly closed with a closing brace.
- Every array must be properly closed with a closing bracket.
- Do NOT use single quotes. Do NOT leave trailing commas.
- Escape any double quotes inside string values with a backslash: \\"
- If you are running out of space, close all open arrays and objects cleanly.
  Do NOT truncate mid-string. Better to have fewer items than broken JSON.

OUTPUT FORMAT:

{
  "worldview_pillars": [
    {
      "pillar": "name of this root belief",
      "statement": "his belief in one sentence",
      "appears_in_n_videos": 0,
      "child_concepts": ["concept name"]
    }
  ],
  "deduplicated_frameworks": [
    {
      "name": "canonical framework name",
      "description": "merged description",
      "steps": ["step 1", "step 2"],
      "appears_in_videos": ["video title 1"],
      "frequency": 0,
      "related_models": ["[[Model Name]]"],
      "related_tactics": ["[[Tactic Name]]"]
    }
  ],
  "deduplicated_mental_models": [
    {
      "name": "canonical model name",
      "description": "merged description",
      "application": "how to use it",
      "appears_in_videos": ["video title"],
      "frequency": 0,
      "is_core_belief": false,
      "related_frameworks": ["[[Framework Name]]"],
      "best_quote": "the strongest verbatim quote across all videos"
    }
  ],
  "deduplicated_tactics": [
    {
      "action": "canonical tactic",
      "context": "when to use",
      "outcome": "expected result",
      "appears_in_videos": ["video title"],
      "frequency": 0,
      "implements_framework": "[[Framework Name]] or null"
    }
  ],
  "deduplicated_mindset_principles": [
    {
      "principle": "canonical principle",
      "reframe": "conventional vs hormozi belief",
      "appears_in_videos": ["video title"],
      "frequency": 0,
      "is_core_belief": false,
      "best_quote": "strongest verbatim quote"
    }
  ],
  "domain_mocs": {
    "sales": ["[[Node Name 1]]"],
    "offers": [],
    "pricing": [],
    "marketing": [],
    "hiring": [],
    "operations": [],
    "mindset": [],
    "identity": [],
    "productivity": [],
    "scaling": [],
    "money": [],
    "relationships": [],
    "content": [],
    "persuasion": [],
    "leadership": [],
    "investing": [],
    "health": [],
    "learning": []
  }
}
"""

SYNTHESIS_USER = """
Here are {count} extraction JSONs from Hormozi transcripts. Synthesize them.
Return ONLY valid JSON. No markdown. No backticks. No preamble.
If you must truncate due to length, close all open arrays/objects properly first.

{extractions}
"""

# ════════════════════════════════════════════════════════════════
#  OLLAMA CLIENT
# ════════════════════════════════════════════════════════════════

def call_ollama(system_prompt, user_prompt, retries=MAX_RETRIES):
    for attempt in range(retries):
        try:
            content, _ = ollama_chat(
                messages=[{"role": "user", "content": user_prompt}],
                system=system_prompt,
                temperature=0.1,
                num_predict=8192,
            )
            return content
        except Exception as e:
            wait = (attempt + 1) * 10
            print(f"\n  ⚠  Attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"All {retries} attempts failed.")

# ════════════════════════════════════════════════════════════════
#  JSON REPAIR ENGINE  (new in v2)
# ════════════════════════════════════════════════════════════════

def repair_json(raw: str) -> dict:
    """
    Multi-stage JSON repair pipeline.
    Attempts 4 increasingly aggressive strategies before giving up.
    """

    # ── Stage 0: strip markdown fences ───────────────────────
    text = raw.strip()
    text = re.sub(r"^```[a-z]*\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    # ── Stage 1: direct parse (ideal case) ───────────────────
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # ── Stage 2: common fixes ─────────────────────────────────
    #   a) trailing commas before } or ]
    #   b) missing comma between } { or ] [
    #   c) single-quoted strings → double-quoted
    fixed = text
    fixed = re.sub(r",\s*([}\]])", r"\1", fixed)           # trailing commas
    fixed = re.sub(r"}\s*{", r"},{", fixed)                 # missing comma obj
    fixed = re.sub(r"]\s*\[", r"],[", fixed)                # missing comma arr
    fixed = re.sub(r"}\s*\[", r"},[", fixed)                # missing comma mixed
    fixed = re.sub(r"]\s*{", r"],{", fixed)                 # missing comma mixed
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # ── Stage 3: truncate at last valid complete object ───────
    # Find the last position where the JSON was still valid by
    # walking backwards from the end to find a clean closing brace
    for end_pos in range(len(fixed), 0, -1):
        candidate = fixed[:end_pos].rstrip()
        # Try to close the JSON cleanly
        open_braces  = candidate.count("{") - candidate.count("}")
        open_brackets = candidate.count("[") - candidate.count("]")
        closing = "}" * max(0, open_braces) + "]" * max(0, open_brackets)
        # This naive close won't always work but catches many cases
        attempt = candidate
        # Walk back to last } or ] to get a clean boundary
        if candidate.endswith((",", ":")):
            candidate = candidate[:-1].rstrip()
        # Close open arrays/objects
        depth_stack = []
        for ch in candidate:
            if ch in "{[":
                depth_stack.append(ch)
            elif ch == "}" and depth_stack and depth_stack[-1] == "{":
                depth_stack.pop()
            elif ch == "]" and depth_stack and depth_stack[-1] == "[":
                depth_stack.pop()
        closing_chars = ""
        for ch in reversed(depth_stack):
            closing_chars += "}" if ch == "{" else "]"
        recovered = candidate + closing_chars
        try:
            result = json.loads(recovered)
            print(f"\n  🔧 JSON recovered via truncation (lost ~{len(fixed)-end_pos} chars)")
            return result
        except json.JSONDecodeError:
            continue

    # ── Stage 4: extract partial valid keys manually ──────────
    # Build a minimal valid synthesis shell from whatever top-level
    # keys we can find using regex
    print(f"\n  🔧 Attempting partial key extraction...")
    shell = _extract_partial_keys(fixed)
    if shell:
        return shell

    # ── Total failure ─────────────────────────────────────────
    raise ValueError("JSON repair failed through all 4 stages.")


def _extract_partial_keys(text: str) -> dict:
    """
    Last-resort: try to extract individual top-level keys from broken JSON.
    Returns a partial synthesis dict with whatever could be salvaged.
    """
    EMPTY_SYNTHESIS = {
        "worldview_pillars": [],
        "deduplicated_frameworks": [],
        "deduplicated_mental_models": [],
        "deduplicated_tactics": [],
        "deduplicated_mindset_principles": [],
        "domain_mocs": {
            d: [] for d in [
                "sales","offers","pricing","marketing","hiring","operations",
                "mindset","identity","productivity","scaling","money",
                "relationships","content","persuasion","leadership",
                "investing","health","learning"
            ]
        }
    }

    result = dict(EMPTY_SYNTHESIS)
    recovered_any = False

    for key in EMPTY_SYNTHESIS.keys():
        if key == "domain_mocs":
            continue
        # Find the key and try to parse its array value
        pattern = rf'"{key}"\s*:\s*(\[)'
        match = re.search(pattern, text)
        if not match:
            continue
        start = match.start(1)
        # Scan forward counting brackets
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start):
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        try:
            arr = json.loads(text[start:end])
            result[key] = arr
            recovered_any = True
            print(f"    ✓ Recovered key: {key} ({len(arr)} items)")
        except Exception:
            pass

    return result if recovered_any else None

# ════════════════════════════════════════════════════════════════
#  CACHE HELPERS  (unchanged from v1)
# ════════════════════════════════════════════════════════════════

def _cache_hash(filename: str) -> str:
    return hashlib.md5(filename.encode("utf-8")).hexdigest()[:12]


def cache_path(filename: str) -> Path:
    """Short hash-only path — avoids Windows MAX_PATH failures on long filenames."""
    return Path(CACHE_DIR) / f"{_cache_hash(filename)}.json"


def legacy_cache_path(filename: str) -> Path:
    h = hashlib.md5(filename.encode("utf-8")).hexdigest()[:8]
    return Path(CACHE_DIR) / f"{h}_{Path(filename).stem}.json"


def resolve_cache_path(filename: str) -> Path | None:
    short = cache_path(filename)
    if short.exists():
        return short
    legacy = legacy_cache_path(filename)
    if legacy.exists():
        return legacy
    return None


def is_cached(filename: str) -> bool:
    return resolve_cache_path(filename) is not None


def save_cache(filename: str, data: dict):
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    cache_path(filename).write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_cache(filename: str) -> dict:
    path = resolve_cache_path(filename)
    if path is None:
        raise FileNotFoundError(f"No cache for {filename}")
    return json.loads(path.read_text(encoding="utf-8"))

# ════════════════════════════════════════════════════════════════
#  PHASE 1 — PER-TRANSCRIPT EXTRACTION  (unchanged from v1)
# ════════════════════════════════════════════════════════════════

def phase1_extract() -> list:
    transcripts = sorted(Path(TRANSCRIPTS_DIR).glob("*.md"))
    total = len(transcripts)

    if total == 0:
        print(f"❌  No .md files found in '{TRANSCRIPTS_DIR}'")
        exit(1)

    print(f"\n{'═'*60}")
    print(f"  PHASE 1 — Extracting from {total} transcripts")
    print(f"  Model: {MODEL}  |  Delay: {DELAY_BETWEEN_CALLS}s between calls")
    print(f"{'═'*60}\n")

    cached_count = sum(1 for t in transcripts if is_cached(t.name))
    new_count = total - cached_count

    print(f"  📊 {cached_count} cached  |  {new_count} new to extract")
    if new_count > 0:
        print(f"  ⏱  Estimated time for new: ~{(new_count * (DELAY_BETWEEN_CALLS + 6)) // 60} minutes")
    print()

    if new_count > 0:
        confirm = input("  Proceed with Phase 1? (y/n): ").strip().lower()
        if confirm != "y":
            print("  Aborted.")
            exit(0)
    else:
        print("  All transcripts cached — skipping Phase 1 API calls.\n")

    extractions = []
    skipped = 0
    failed = []

    for i, path in enumerate(transcripts, 1):
        filename = path.name
        prefix = f"  [{i:03d}/{total}]"

        if is_cached(filename):
            data = load_cache(filename)
            extractions.append(data)
            skipped += 1
            print(f"{prefix} ✓ (cached)  {filename[:55]}")
            continue

        print(f"{prefix} ⟳ extracting  {filename[:55]}", end="", flush=True)

        transcript_text = path.read_text(encoding="utf-8")
        if len(transcript_text) > 900_000:
            transcript_text = transcript_text[:900_000]
            print(f" [trimmed]", end="")

        user_prompt = EXTRACTION_USER.format(
            filename=filename,
            transcript=transcript_text
        )

        try:
            raw = call_ollama(EXTRACTION_SYSTEM, user_prompt)
            data = repair_json(raw)
            data["_source_file"] = filename
            save_cache(filename, data)
            extractions.append(data)
            print(f"  ✓")
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            failed.append(filename)

        time.sleep(DELAY_BETWEEN_CALLS)

    print(f"\n  Phase 1 complete.")
    print(f"  ✓ Extracted: {new_count - len(failed)} new  |  {skipped} from cache  |  {len(failed)} failed")

    if failed:
        print(f"\n  ⚠  Failed files:")
        for f in failed:
            print(f"    - {f}")

    return extractions

# ════════════════════════════════════════════════════════════════
#  PHASE 2 — SYNTHESIS  (rewritten in v2)
# ════════════════════════════════════════════════════════════════

def run_synthesis_batch(batch: list, label: str) -> dict | None:
    """
    Run one synthesis call with full repair pipeline.
    Returns parsed dict or None on total failure.
    """
    user_prompt = SYNTHESIS_USER.format(
        count=len(batch),
        extractions=json.dumps(batch, indent=2)
    )
    try:
        raw = call_ollama(SYNTHESIS_SYSTEM, user_prompt)
        return repair_json(raw)
    except Exception as e:
        print(f"\n  ✗ {label} failed after repair: {e}")
        # Save raw output for manual inspection
        raw_path = Path(CACHE_DIR) / f"raw_{label.replace(' ', '_')}.txt"
        try:
            raw_path.write_text(raw, encoding="utf-8")
            print(f"    Raw output saved to: {raw_path}")
        except Exception:
            pass
        return None


def merge_synthesis_results(results: list) -> dict:
    """
    Merge multiple partial synthesis dicts into one.
    Concatenates all lists, sums frequencies, merges domain_mocs.
    """
    DOMAIN_KEYS = [
        "sales","offers","pricing","marketing","hiring","operations",
        "mindset","identity","productivity","scaling","money",
        "relationships","content","persuasion","leadership",
        "investing","health","learning"
    ]

    merged = {
        "worldview_pillars": [],
        "deduplicated_frameworks": [],
        "deduplicated_mental_models": [],
        "deduplicated_tactics": [],
        "deduplicated_mindset_principles": [],
        "domain_mocs": {d: [] for d in DOMAIN_KEYS}
    }

    for r in results:
        if not r:
            continue
        for key in ["worldview_pillars", "deduplicated_frameworks",
                    "deduplicated_mental_models", "deduplicated_tactics",
                    "deduplicated_mindset_principles"]:
            merged[key].extend(r.get(key, []))

        mocs = r.get("domain_mocs", {})
        for domain in DOMAIN_KEYS:
            existing = set(merged["domain_mocs"][domain])
            for node in mocs.get(domain, []):
                if node not in existing:
                    merged["domain_mocs"][domain].append(node)
                    existing.add(node)

    return merged


def phase2_synthesize(extractions: list) -> dict:
    print(f"\n{'═'*60}")
    print(f"  PHASE 2 — Synthesizing {len(extractions)} extractions")
    print(f"  Initial batch size: {SYNTHESIS_BATCH} | Retry batch size: {SYNTHESIS_HALF}")
    print(f"{'═'*60}\n")

    # Check for final synthesis cache
    synthesis_cache = Path(CACHE_DIR) / "synthesis_final.json"
    if synthesis_cache.exists():
        print("  ✓ Final synthesis cache found — loading...")
        return json.loads(synthesis_cache.read_text(encoding="utf-8"))

    # Split into initial batches
    batches = [
        extractions[i:i + SYNTHESIS_BATCH]
        for i in range(0, len(extractions), SYNTHESIS_BATCH)
    ]
    total_batches = len(batches)

    batch_results = []
    failed_batches = []

    for i, batch in enumerate(batches, 1):
        batch_cache = Path(CACHE_DIR) / f"synthesis_batch_{i}.json"
        label = f"batch {i}/{total_batches}"

        # Load from cache if available
        if batch_cache.exists():
            print(f"  [{i}/{total_batches}] ✓ (cached) {label}")
            batch_results.append(json.loads(batch_cache.read_text(encoding="utf-8")))
            continue

        # ── First attempt at full batch ───────────────────────
        print(f"  [{i}/{total_batches}] ⟳ synthesizing {label} ({len(batch)} items)...", end="", flush=True)
        result = run_synthesis_batch(batch, label)
        time.sleep(DELAY_BETWEEN_CALLS * 2)

        if result:
            batch_cache.write_text(json.dumps(result, indent=2), encoding="utf-8")
            batch_results.append(result)
            print(f"  ✓")
            continue

        # ── Retry: split into two half-batches ────────────────
        print(f"\n  ↳ Retrying {label} as two half-batches ({SYNTHESIS_HALF} items each)...")
        half_a = batch[:SYNTHESIS_HALF]
        half_b = batch[SYNTHESIS_HALF:]
        sub_results = []

        for j, half in enumerate([half_a, half_b], 1):
            if not half:
                continue
            half_label = f"batch {i} half-{j}"
            half_cache = Path(CACHE_DIR) / f"synthesis_batch_{i}_half{j}.json"

            if half_cache.exists():
                print(f"    ✓ (cached) {half_label}")
                sub_results.append(json.loads(half_cache.read_text(encoding="utf-8")))
                continue

            print(f"    ⟳ {half_label} ({len(half)} items)...", end="", flush=True)
            sub_result = run_synthesis_batch(half, half_label)
            time.sleep(DELAY_BETWEEN_CALLS * 2)

            if sub_result:
                half_cache.write_text(json.dumps(sub_result, indent=2), encoding="utf-8")
                sub_results.append(sub_result)
                print(f"  ✓")
            else:
                print(f"  ✗ (skipped)")
                failed_batches.append(half_label)

        if sub_results:
            # Merge the two half results into one batch result
            merged_halves = merge_synthesis_results(sub_results)
            batch_cache.write_text(json.dumps(merged_halves, indent=2), encoding="utf-8")
            batch_results.append(merged_halves)
            print(f"  ↳ {label} recovered from half-batches ✓")
        else:
            failed_batches.append(label)
            print(f"  ↳ {label} totally failed — skipping.")

    # ── Final merge ───────────────────────────────────────────
    if not batch_results:
        print("  ❌  All synthesis batches failed. Using empty synthesis shell.")
        print("      Phase 3 will still run using raw extractions only.")
        final = merge_synthesis_results([])
    elif len(batch_results) == 1:
        final = batch_results[0]
        print(f"\n  ⟳ Single batch — no merge needed.")
    else:
        print(f"\n  ⟳ Merging {len(batch_results)} successful batch syntheses...", end="", flush=True)

        # Try an Ollama-powered final merge first
        merge_cache = Path(CACHE_DIR) / "synthesis_merge.json"
        if merge_cache.exists():
            final = json.loads(merge_cache.read_text(encoding="utf-8"))
            print(f" ✓ (cached)")
        else:
            merge_prompt = f"""
You have {len(batch_results)} partial synthesis JSONs from batches of Alex Hormozi transcripts.
Merge them into ONE final synthesis JSON following the exact same schema.
- Deduplicate across batches (same concept appearing in multiple batches → one entry)
- Sum the frequency counts across batches
- Keep the richest/most complete version of each node
- Merge all domain_mocs lists, removing duplicates
Return ONLY valid JSON. No markdown. No backticks. No preamble.
If you must truncate, close all open arrays and objects cleanly first.

PARTIAL SYNTHESES:
{json.dumps(batch_results, indent=2)}
"""
            try:
                raw = call_ollama(SYNTHESIS_SYSTEM, merge_prompt)
                final = repair_json(raw)
                merge_cache.write_text(json.dumps(final, indent=2), encoding="utf-8")
                print(f"  ✓")
            except Exception as e:
                print(f"  ✗ Ollama merge failed ({e}) — using Python merge fallback")
                final = merge_synthesis_results(batch_results)

    # Save final
    synthesis_cache.write_text(json.dumps(final, indent=2), encoding="utf-8")

    # Summary
    print(f"\n  Phase 2 complete.")
    if failed_batches:
        print(f"  ⚠  Failed (skipped): {len(failed_batches)} sub-batches")
        for fb in failed_batches:
            print(f"    - {fb}")
    print(f"  ✓ Frameworks extracted:        {len(final.get('deduplicated_frameworks', []))}")
    print(f"  ✓ Mental models extracted:     {len(final.get('deduplicated_mental_models', []))}")
    print(f"  ✓ Tactics extracted:           {len(final.get('deduplicated_tactics', []))}")
    print(f"  ✓ Mindset principles extracted:{len(final.get('deduplicated_mindset_principles', []))}")
    print(f"  ✓ Worldview pillars:           {len(final.get('worldview_pillars', []))}")

    return final

# ════════════════════════════════════════════════════════════════
#  PHASE 3 — OBSIDIAN VAULT ASSEMBLY  (unchanged from v1)
# ════════════════════════════════════════════════════════════════

VAULT_DIRS = [
    "00 MOCs",
    "01 Frameworks",
    "02 Mental Models",
    "03 Tactics",
    "04 Mindset Principles",
    "05 Stories & Analogies",
    "06 Quotes",
    "07 Source Notes",
]

def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip().strip(".")
    return name[:120] if len(name) > 120 else name

def make_tags(domains: list) -> str:
    return " ".join(f"#{d}" for d in domains if d)

def make_frontmatter(title: str, tags: list, node_type: str, frequency: int = 0) -> str:
    tag_str = "\n".join(f"  - {t}" for t in tags)
    freq_line = f"frequency: {frequency}\n" if frequency else ""
    return f"""---
title: "{title}"
type: {node_type}
tags:
{tag_str}
{freq_line}created: {datetime.today().strftime('%Y-%m-%d')}
source: Alex Hormozi
---

"""

def write_note(folder: str, filename: str, content: str):
    if folder:
        path = Path(OUTPUT_DIR) / folder / f"{safe_filename(filename)}.md"
    else:
        path = Path(OUTPUT_DIR) / f"{safe_filename(filename)}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def phase3_assemble(extractions: list, synthesis: dict):
    print(f"\n{'═'*60}")
    print(f"  PHASE 3 — Assembling Obsidian vault")
    print(f"  Output: {OUTPUT_DIR}/")
    print(f"{'═'*60}\n")

    for d in VAULT_DIRS:
        (Path(OUTPUT_DIR) / d).mkdir(parents=True, exist_ok=True)

    note_count = 0

    # ── 01 Frameworks ─────────────────────────────────────────
    for fw in synthesis.get("deduplicated_frameworks", []):
        name = fw.get("name", "Unnamed Framework")
        freq = fw.get("frequency", 0)
        videos = fw.get("appears_in_videos", [])
        steps = fw.get("steps", [])
        related_models = fw.get("related_models", [])
        related_tactics = fw.get("related_tactics", [])
        desc = fw.get("description", "")

        steps_md = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps)) if steps else "_No steps extracted._"
        related_md_m = "\n".join(f"- {r}" for r in related_models) if related_models else "_None_"
        related_md_t = "\n".join(f"- {r}" for r in related_tactics) if related_tactics else "_None_"
        sources_md = "\n".join(f"- [[07 Source Notes/{safe_filename(v)}|{v}]]" for v in videos) if videos else "_Unknown_"
        core_badge = "\n> 🔑 **Core Framework** — appears in multiple videos\n" if freq >= 3 else ""

        content = make_frontmatter(name, ["framework"], "framework", freq)
        content += f"# {name}\n\n"
        content += core_badge
        content += f"## What It Is\n{desc}\n\n"
        content += f"## Steps\n{steps_md}\n\n"
        content += f"## Related Mental Models\n{related_md_m}\n\n"
        content += f"## Related Tactics\n{related_md_t}\n\n"
        content += f"## Appears In ({freq} videos)\n{sources_md}\n"

        write_note("01 Frameworks", name, content)
        note_count += 1

    # ── 02 Mental Models ──────────────────────────────────────
    for mm in synthesis.get("deduplicated_mental_models", []):
        name = mm.get("name", "Unnamed Model")
        freq = mm.get("frequency", 0)
        is_core = mm.get("is_core_belief", False)
        videos = mm.get("appears_in_videos", [])
        related_fw = mm.get("related_frameworks", [])
        best_quote = mm.get("best_quote", "")

        related_md = "\n".join(f"- {r}" for r in related_fw) if related_fw else "_None_"
        sources_md = "\n".join(f"- [[07 Source Notes/{safe_filename(v)}|{v}]]" for v in videos) if videos else "_Unknown_"
        core_badge = "\n> 🧠 **Core Belief** — foundational to Hormozi's worldview\n" if is_core else ""

        content = make_frontmatter(name, ["mental-model"], "mental-model", freq)
        content += f"# {name}\n\n"
        content += core_badge
        content += f"> {best_quote}\n\n" if best_quote else ""
        content += f"## Description\n{mm.get('description', '')}\n\n"
        content += f"## How to Apply\n{mm.get('application', '')}\n\n"
        content += f"## Related Frameworks\n{related_md}\n\n"
        content += f"## Appears In ({freq} videos)\n{sources_md}\n"

        write_note("02 Mental Models", name, content)
        note_count += 1

    # ── 03 Tactics ────────────────────────────────────────────
    for tc in synthesis.get("deduplicated_tactics", []):
        action = tc.get("action", "Unnamed Tactic")
        freq = tc.get("frequency", 0)
        videos = tc.get("appears_in_videos", [])
        implements = tc.get("implements_framework")

        sources_md = "\n".join(f"- [[07 Source Notes/{safe_filename(v)}|{v}]]" for v in videos) if videos else "_Unknown_"
        impl_md = f"- {implements}" if implements else "_Standalone tactic_"

        content = make_frontmatter(action, ["tactic"], "tactic", freq)
        content += f"# {action}\n\n"
        content += f"## When to Use\n{tc.get('context', '')}\n\n"
        content += f"## Expected Outcome\n{tc.get('outcome', '')}\n\n"
        content += f"## Part of Framework\n{impl_md}\n\n"
        content += f"## Appears In ({freq} videos)\n{sources_md}\n"

        write_note("03 Tactics", action, content)
        note_count += 1

    # ── 04 Mindset Principles ─────────────────────────────────
    for mp in synthesis.get("deduplicated_mindset_principles", []):
        principle = mp.get("principle", "Unnamed Principle")
        freq = mp.get("frequency", 0)
        is_core = mp.get("is_core_belief", False)
        videos = mp.get("appears_in_videos", [])
        best_quote = mp.get("best_quote", "")
        reframe = mp.get("reframe", "")

        sources_md = "\n".join(f"- [[07 Source Notes/{safe_filename(v)}|{v}]]" for v in videos) if videos else "_Unknown_"
        core_badge = "\n> 💡 **Core Identity Belief**\n" if is_core else ""

        content = make_frontmatter(principle, ["mindset"], "mindset-principle", freq)
        content += f"# {principle}\n\n"
        content += core_badge
        content += f"> {best_quote}\n\n" if best_quote else ""
        content += f"## The Reframe\n{reframe}\n\n" if reframe else ""
        content += f"## Appears In ({freq} videos)\n{sources_md}\n"

        write_note("04 Mindset Principles", principle, content)
        note_count += 1

    # ── 05 Stories & Analogies ────────────────────────────────
    seen_stories = set()
    for ex in extractions:
        source = ex.get("_source_file", "")
        video_title = ex.get("video_title", Path(source).stem)
        for st in ex.get("stories_analogies", []):
            title = st.get("title", "Untitled Story")
            key = title.lower().strip()
            if key in seen_stories:
                continue
            seen_stories.add(key)

            content = make_frontmatter(title, ["story", "analogy"], "story")
            content += f"# {title}\n\n"
            content += f"> {st.get('quote', '')}\n\n" if st.get("quote") else ""
            content += f"## The Story\n{st.get('narrative', '')}\n\n"
            content += f"## What It Illustrates\n{st.get('lesson', '')}\n\n"
            content += f"## Source\n[[07 Source Notes/{safe_filename(video_title)}|{video_title}]]\n"

            write_note("05 Stories & Analogies", title, content)
            note_count += 1

    # ── 06 Quotes ─────────────────────────────────────────────
    all_quotes = []
    for ex in extractions:
        source = ex.get("_source_file", "")
        video_title = ex.get("video_title", Path(source).stem)
        for q in ex.get("quotes", []):
            all_quotes.append({**q, "_video": video_title})

    type_order = {"counterintuitive": 0, "identity": 1, "provocative": 2, "instructional": 3}
    all_quotes.sort(key=lambda q: type_order.get(q.get("punchline_type", ""), 9))

    quotes_content = make_frontmatter("All Quotes", ["quotes"], "quote-index")
    quotes_content += "# Hormozi Quotes\n\n"
    quotes_content += "_Sorted by impact type: counterintuitive → identity → provocative → instructional_\n\n"

    for q in all_quotes:
        ptype = q.get("punchline_type", "")
        badge = {"counterintuitive": "🔄", "identity": "🪞", "provocative": "⚡", "instructional": "📌"}.get(ptype, "💬")
        quotes_content += f"---\n\n{badge} **{q.get('text', '')}**\n\n"
        quotes_content += f"_Context: {q.get('context', '')}_ — [[07 Source Notes/{safe_filename(q['_video'])}|{q['_video']}]]\n\n"

    write_note("06 Quotes", "All Quotes", quotes_content)
    note_count += 1

    # ── 07 Source Notes ───────────────────────────────────────
    for ex in extractions:
        source = ex.get("_source_file", "")
        video_title = ex.get("video_title", Path(source).stem)
        domains = ex.get("domains", [])
        core_idea = ex.get("core_idea", "")

        fw_links = "\n".join(
            f"- [[01 Frameworks/{safe_filename(f['name'])}|{f['name']}]]"
            for f in ex.get("frameworks", [])
        ) or "_None_"

        mm_links = "\n".join(
            f"- [[02 Mental Models/{safe_filename(m['name'])}|{m['name']}]]"
            for m in ex.get("mental_models", [])
        ) or "_None_"

        tc_links = "\n".join(
            f"- [[03 Tactics/{safe_filename(t['action'])}|{t['action']}]]"
            for t in ex.get("tactics", [])
        ) or "_None_"

        content = make_frontmatter(video_title, domains + ["source-note"], "source-note")
        content += f"# {video_title}\n\n"
        content += f"**Core Idea:** {core_idea}\n\n" if core_idea else ""
        content += f"**Domains:** {make_tags(domains)}\n\n"
        content += f"## Frameworks Introduced\n{fw_links}\n\n"
        content += f"## Mental Models\n{mm_links}\n\n"
        content += f"## Tactics\n{tc_links}\n\n"
        content += f"**Source file:** `{source}`\n"

        write_note("07 Source Notes", video_title, content)
        note_count += 1

    # ── 00 MOCs ───────────────────────────────────────────────
    domain_mocs = synthesis.get("domain_mocs", {})

    for domain, nodes in domain_mocs.items():
        if not nodes:
            continue
        moc_content = make_frontmatter(f"{domain.title()} MOC", [domain, "moc"], "moc")
        moc_content += f"# {domain.title()} — Map of Content\n\n"
        moc_content += f"_All Hormozi knowledge nodes tagged `#{domain}`, sorted by frequency._\n\n"
        for node in nodes:
            moc_content += f"- {node}\n"
        write_note("00 MOCs", f"{domain.title()} MOC", moc_content)
        note_count += 1

    # ── Worldview Pillars ─────────────────────────────────────
    pillars = synthesis.get("worldview_pillars", [])
    if pillars:
        pillars_content = make_frontmatter("Hormozi Worldview Pillars", ["worldview", "moc"], "moc")
        pillars_content += "# Hormozi's Worldview Pillars\n\n"
        pillars_content += "_The root beliefs that underpin everything he teaches._\n\n"
        for p in pillars:
            name = p.get("pillar", "")
            statement = p.get("statement", "")
            freq = p.get("appears_in_n_videos", 0)
            children = p.get("child_concepts", [])
            def _link_target(name: str) -> str:
                n = name.strip()
                while n.startswith("["):
                    n = n[1:]
                while n.endswith("]"):
                    n = n[:-1]
                return n.strip()

            children_md = (
                ", ".join(f"[[{_link_target(c)}]]" for c in children) if children else ""
            )
            pillars_content += f"## {name}\n> {statement}\n\n"
            pillars_content += f"_Appears in {freq} videos_\n\n"
            if children_md:
                pillars_content += f"**Related concepts:** {children_md}\n\n"
        write_note("00 MOCs", "Hormozi Worldview Pillars", pillars_content)
        note_count += 1

    # ── Master Index ──────────────────────────────────────────
    index_content = f"""---
title: "Hormozi Brain — Master Index"
type: index
created: {datetime.today().strftime('%Y-%m-%d')}
---

# 🧠 Hormozi Brain

> Built from {len(extractions)} transcripts. {note_count} knowledge nodes.

## Navigate by Category

- [[00 MOCs/Hormozi Worldview Pillars|🏛 Worldview Pillars]] — root beliefs
- [[01 Frameworks/|⚙️ Frameworks]] — named systems and models
- [[02 Mental Models/|🧩 Mental Models]] — how he thinks
- [[03 Tactics/|🎯 Tactics]] — specific executable moves
- [[04 Mindset Principles/|💡 Mindset Principles]] — identity & beliefs
- [[05 Stories & Analogies/|📖 Stories & Analogies]] — parables he uses
- [[06 Quotes/All Quotes|💬 Quotes]] — verbatim punchlines
- [[07 Source Notes/|📼 Source Notes]] — one note per video

## Navigate by Domain

"""
    for domain in sorted(domain_mocs.keys()):
        if domain_mocs.get(domain):
            index_content += f"- [[00 MOCs/{domain.title()} MOC|#{domain}]]\n"

    index_content += f"\n---\n_Generated: {datetime.today().strftime('%Y-%m-%d %H:%M')}_\n"
    write_note("", "🧠 Hormozi Brain Index", index_content)
    note_count += 1

    print(f"  Phase 3 complete.")
    print(f"  📝 Notes written: {note_count}")
    print(f"  📁 Vault location: {Path(OUTPUT_DIR).resolve()}\n")

# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║       HORMOZI BRAIN BUILDER v2 — Obsidian Vault             ║
║       Model: deepseek-v4-flash:cloud via Ollama Cloud       ║
║       Fix: Robust JSON repair + half-batch retry            ║
╚══════════════════════════════════════════════════════════════╝
""")

    if not Path(TRANSCRIPTS_DIR).exists():
        print(f"❌  Transcripts directory not found: '{TRANSCRIPTS_DIR}'")
        exit(1)

    # Delete stale final synthesis so v2 reruns Phase 2 with the fix
    stale = Path(CACHE_DIR) / "synthesis_final.json"
    stale_merge = Path(CACHE_DIR) / "synthesis_merge.json"
    if stale.exists():
        stale.unlink()
        print("  🗑  Cleared stale synthesis_final.json — will resynthesize.")
    if stale_merge.exists():
        stale_merge.unlink()

    extractions = phase1_extract()

    if not extractions:
        print("❌  No extractions produced.")
        exit(1)

    synthesis = phase2_synthesize(extractions)
    phase3_assemble(extractions, synthesis)

    print("═" * 60)
    print("  ✅  BRAIN BUILD COMPLETE (v2)")
    print(f"  Open '{OUTPUT_DIR}' as a vault in Obsidian.")
    print("  Tip: Enable Graph View (Ctrl+G) to see the knowledge web.")
    print("═" * 60)

if __name__ == "__main__":
    main()