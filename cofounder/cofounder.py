"""
╔══════════════════════════════════════════════════════════════════════╗
║           HORMOZI AI COFOUNDER — Core Module                        ║
║           Persona layer on top of the Hormozi Brain                 ║
║           Plugs into: MCP server, Web API, Terminal                 ║
╚══════════════════════════════════════════════════════════════════════╝

EXPOSES 4 FUNCTIONS:
  ask_cofounder(question, domain)  → daily question with full context
  daily_briefing()                 → morning audit, no question needed
  log_decision(...)                → record a decision to the log
  update_context(field, value)     → update startup state

USAGE (terminal):
  python cofounder/cofounder.py

USAGE (module):
  from cofounder.cofounder import ask_cofounder, daily_briefing
"""

# ════════════════════════════════════════════════════════════════
#  CONFIG
# ════════════════════════════════════════════════════════════════

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────
COFOUNDER_DIR   = Path(__file__).parent
CONTEXT_FILE    = COFOUNDER_DIR / "startup_context.json"
DECISION_FILE   = COFOUNDER_DIR / "decision_log.json"

# ── Backend (your Render deployment) ──────────────────────────
BACKEND_URL     = os.getenv("HORMOZI_BACKEND_URL",
                             "https://hormozi-s-transcripts.onrender.com")
AUTH_TOKEN      = os.getenv("HORMOZI_WEB_TOKEN", "").strip() or None

# ── Gemini (for cofounder chat — same key as always) ──────────
GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL    = os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview")

# ── How many past decisions to inject into every prompt ───────
DECISION_HISTORY_LIMIT = 10

try:
    from google import genai
    from google.genai import types as gtypes
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

# ════════════════════════════════════════════════════════════════
#  CONTEXT HELPERS
# ════════════════════════════════════════════════════════════════

def load_context() -> dict:
    if not CONTEXT_FILE.exists():
        raise FileNotFoundError(f"startup_context.json not found at {CONTEXT_FILE}")
    return json.loads(CONTEXT_FILE.read_text(encoding="utf-8"))


def save_context(ctx: dict):
    ctx["last_updated"] = datetime.today().strftime("%Y-%m-%d")
    CONTEXT_FILE.write_text(json.dumps(ctx, indent=2, ensure_ascii=False),
                             encoding="utf-8")


def load_decisions() -> dict:
    if not DECISION_FILE.exists():
        return {"decisions": [], "total_decisions": 0, "last_updated": ""}
    return json.loads(DECISION_FILE.read_text(encoding="utf-8"))


def save_decisions(log: dict):
    log["last_updated"] = datetime.today().strftime("%Y-%m-%d")
    DECISION_FILE.write_text(json.dumps(log, indent=2, ensure_ascii=False),
                              encoding="utf-8")


def format_context_block(ctx: dict) -> str:
    """Format startup context into a readable block for the prompt."""
    f  = ctx.get("founder", {})
    s  = ctx.get("startup", {})
    g  = ctx.get("goals", {})
    st = ctx.get("strategy", {})

    lines = [
        "━━━ YOUR STARTUP CONTEXT ━━━",
        f"Founder       : {f.get('name')} — {f.get('location')}",
        f"Background    : {f.get('background')}",
        f"Partner       : {f.get('partner', 'None')}",
        f"Strengths     : {', '.join(f.get('strengths', []))}",
        f"Constraints   : {', '.join(f.get('constraints', []))}",
        "",
        f"Startup       : {s.get('name') or '(unnamed)'}",
        f"One-liner     : {s.get('one_liner') or '(not defined yet)'}",
        f"Domain        : {s.get('domain')}",
        f"Stage         : {s.get('stage')}",
        f"Target market : {s.get('target_market')}",
        f"Industries    : {', '.join(s.get('target_industries', [])) or 'not selected'}",
        f"Problem       : {s.get('problem_being_solved') or '(not defined)'}",
        f"Current offer : {s.get('current_offer') or '(none)'}",
        f"Pricing       : {s.get('pricing') or '(none)'}",
        f"Revenue       : ₹{s.get('revenue', 0):,}",
        f"Clients       : {len(s.get('clients', []))} active",
        "",
        f"90-day goal   : {g.get('90_day_goal')}",
        f"Revenue target: ₹{g.get('monthly_revenue_target_inr', 0):,}/month",
        f"Current focus : {g.get('current_focus')}",
        "",
        f"GTM strategy  : {st.get('go_to_market')}",
        f"Positioning   : {st.get('positioning')}",
        f"Blockers      : {', '.join(st.get('current_blockers', []))}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def format_decision_block(log: dict, limit: int = DECISION_HISTORY_LIMIT) -> str:
    """Format recent decisions into a readable block for the prompt."""
    decisions = log.get("decisions", [])[-limit:]
    if not decisions:
        return "No decisions logged yet."
    lines = [f"━━━ LAST {len(decisions)} DECISIONS ━━━"]
    for d in reversed(decisions):
        outcome = d.get("outcome") or "pending"
        lines.append(
            f"[{d.get('date')}] #{d.get('id')} {d.get('category', '').upper()}: "
            f"{d.get('question', '')}"
        )
        lines.append(f"  Recommended : {d.get('hormozi_recommendation', '')[:120]}...")
        lines.append(f"  Decided     : {d.get('decision_made', 'pending')}")
        lines.append(f"  Outcome     : {outcome}")
        lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════
#  BRAIN SEARCH  (hits your Render backend)
# ════════════════════════════════════════════════════════════════

def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if AUTH_TOKEN:
        h["Authorization"] = f"Bearer {AUTH_TOKEN}"
    return h


def search_brain(query: str, domain: str = None, top_k: int = 6) -> str:
    """Pull relevant chunks from the Hormozi Brain via Render backend."""
    payload = json.dumps({"query": query, "top_k": top_k,
                          **({"domain": domain} if domain else {})}).encode()
    req = urllib.request.Request(
        f"{BACKEND_URL}/api/search",
        data=payload, headers=_headers(), method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode())
        chunks = data.get("chunks", data.get("results", []))
        if not chunks:
            return "No relevant knowledge found in the brain for this query."
        lines = []
        for i, chunk in enumerate(chunks, 1):
            videos = chunk.get("source_videos", [])
            lines.append(
                f"[{i}] {chunk.get('note_title','?')} "
                f"({chunk.get('note_type','?')}) — {chunk.get('relevance','?')}"
            )
            lines.append(
                f"     Source: {', '.join(videos) if videos else 'Unknown'}"
            )
            text = chunk.get("text", chunk.get("content", ""))
            lines.append(f"     {text[:350]}{'...' if len(text)>350 else ''}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"Brain search unavailable: {e}"


# ════════════════════════════════════════════════════════════════
#  COFOUNDER SYSTEM PROMPT
# ════════════════════════════════════════════════════════════════

COFOUNDER_SYSTEM = """
You are Alex Hormozi — entrepreneur, investor, author of $100M Offers and $100M Leads,
and co-founder of a portfolio doing over $200M/year.

But right now, specifically, you are SAHI'S BUSINESS COFOUNDER.

You have agreed to co-build this venture with Sahi. You have skin in the game.
You are not a coach. You are not an advisor. You are a COFOUNDER.

That means:
- You know everything about the startup (context injected below)
- You remember every major decision made (log injected below)
- You hold Sahi accountable — every single day
- You tell him when he's wrong, when he's wasting time, when he's overthinking
- You are brutally direct because you want this to succeed
- You never encourage bad strategy just to be nice

YOUR COMMUNICATION STYLE AS COFOUNDER:
- Direct. No fluff. No "great question."
- You think in numbered steps when explaining a process
- You call out the real problem, not the surface problem
- You reference past decisions when relevant ("Last week you said X — does this align?")
- You end every answer with ONE specific action Sahi should take today
- Short sentences. High signal. No corporate speak.

YOUR KNOWLEDGE BASE:
You have access to retrieved context from your own extracted knowledge vault —
839 notes from 211 YouTube videos and your books. Use this knowledge to ground
your answers. Always cite which framework or principle you're drawing from.

RULES:
1. Answer using BOTH the startup context AND the retrieved brain knowledge
2. Always end with: "→ YOUR MOVE TODAY: [one specific action]"
3. If Sahi is asking the wrong question, say so and answer the right one
4. Reference past decisions when relevant
5. Never say "it depends" without immediately resolving the dependency
6. Citations go at the end, after the action item
"""


def build_cofounder_prompt(question: str, ctx: dict, log: dict,
                            brain_context: str) -> str:
    return f"""
{format_context_block(ctx)}

{format_decision_block(log)}

━━━ RETRIEVED KNOWLEDGE FROM YOUR BRAIN ━━━
{brain_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

━━━ SAHI'S QUESTION ━━━
{question}
━━━━━━━━━━━━━━━━━━━━━
"""


BRIEFING_QUESTION = """
Do a morning audit of this startup. No question from Sahi — this is your
daily cofounder check-in.

Cover:
1. What is the ONE most important thing Sahi should do today given the current stage?
2. What is the biggest risk right now that he might be ignoring?
3. Is the current strategy aligned with the 90-day goal? If not, what needs to change?
4. What decision has been delayed too long and needs to be made today?

Be specific. Be direct. No encouragement unless it's earned.
End with: → YOUR MOVE TODAY: [one specific action]
"""

# ════════════════════════════════════════════════════════════════
#  GEMINI CALL
# ════════════════════════════════════════════════════════════════

def _call_gemini(prompt: str) -> str:
    if not GEMINI_AVAILABLE:
        return "❌ google-genai not installed. Run: pip install google-genai"
    if not GEMINI_API_KEY:
        return "❌ Set GEMINI_API_KEY as an environment variable."
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=gtypes.GenerateContentConfig(
            system_instruction=COFOUNDER_SYSTEM,
            temperature=0.4,
            max_output_tokens=2048,
        )
    )
    return response.text


# ════════════════════════════════════════════════════════════════
#  PUBLIC API  (used by MCP, web app, terminal)
# ════════════════════════════════════════════════════════════════

def ask_cofounder(question: str, domain: str = None) -> dict:
    """
    Ask Hormozi a question as your cofounder.
    Returns answer + citations + action item.

    Args:
        question : your question
        domain   : optional Hormozi brain domain filter

    Returns:
        {
          "answer":   str,
          "action":   str,   # the "YOUR MOVE TODAY" line
          "sources":  list,  # brain chunks used
          "question": str
        }
    """
    ctx = load_context()
    log = load_decisions()

    # Search brain for relevant knowledge
    brain_context = search_brain(question, domain=domain)

    # Build and send prompt
    full_prompt = build_cofounder_prompt(question, ctx, log, brain_context)
    raw_answer  = _call_gemini(full_prompt)

    # Extract action item
    action = ""
    for line in raw_answer.splitlines():
        if "YOUR MOVE TODAY" in line:
            action = line.replace("→", "").replace("YOUR MOVE TODAY:", "").strip()
            break

    return {
        "question": question,
        "answer":   raw_answer,
        "action":   action,
        "domain":   domain,
        "context_snapshot": {
            "stage":   ctx.get("startup", {}).get("stage"),
            "focus":   ctx.get("goals", {}).get("current_focus"),
            "revenue": ctx.get("startup", {}).get("revenue", 0),
        }
    }


def daily_briefing() -> dict:
    """
    Morning cofounder audit — no question needed.
    Hormozi reviews the startup state and tells Sahi what to do today.

    Returns:
        {
          "briefing": str,
          "action":   str,
          "date":     str
        }
    """
    ctx = load_context()
    log = load_decisions()

    brain_context = search_brain(
        ctx.get("goals", {}).get("current_focus", "startup strategy"),
        top_k=5
    )

    full_prompt = build_cofounder_prompt(BRIEFING_QUESTION, ctx, log, brain_context)
    raw_answer  = _call_gemini(full_prompt)

    action = ""
    for line in raw_answer.splitlines():
        if "YOUR MOVE TODAY" in line:
            action = line.replace("→", "").replace("YOUR MOVE TODAY:", "").strip()
            break

    return {
        "date":     datetime.today().strftime("%Y-%m-%d"),
        "briefing": raw_answer,
        "action":   action,
    }


def log_decision(
    question:                str,
    options_considered:      list,
    hormozi_recommendation:  str,
    decision_made:           str,
    category:                str = "strategy",
    outcome:                 str = None,
    follow_up:               str = None,
) -> dict:
    """
    Log a major decision to the decision log.

    Args:
        question               : the decision that needed to be made
        options_considered     : list of options that were on the table
        hormozi_recommendation : what Hormozi said to do
        decision_made          : what Sahi actually decided
        category               : one of: strategy / product / market / hiring / finance
        outcome                : result of the decision (fill in later)
        follow_up              : next action required

    Returns:
        {"logged": True, "decision_id": int, "entry": dict}
    """
    log  = load_decisions()
    next_id = len(log.get("decisions", [])) + 1

    entry = {
        "id":                      next_id,
        "date":                    datetime.today().strftime("%Y-%m-%d"),
        "category":                category,
        "question":                question,
        "options_considered":      options_considered,
        "hormozi_recommendation":  hormozi_recommendation,
        "decision_made":           decision_made,
        "outcome":                 outcome,
        "follow_up":               follow_up,
    }

    log.setdefault("decisions", []).append(entry)
    log["total_decisions"] = len(log["decisions"])
    save_decisions(log)

    return {"logged": True, "decision_id": next_id, "entry": entry}


def update_context(field_path: str, value) -> dict:
    """
    Update a field in startup_context.json.

    Args:
        field_path : dot-notation path e.g. 'startup.name' or 'goals.current_focus'
        value      : new value (string, number, list, etc.)

    Returns:
        {"updated": True, "field": str, "value": value}

    Examples:
        update_context('startup.name', 'Sahi AI Solutions')
        update_context('startup.target_industries', ['logistics', 'healthcare'])
        update_context('startup.revenue', 50000)
        update_context('goals.current_focus', 'Closing first client')
        update_context('strategy.current_blockers', ['Need case study'])
    """
    ctx    = load_context()
    keys   = field_path.split(".")
    target = ctx

    # Navigate to the parent
    for key in keys[:-1]:
        if key not in target:
            target[key] = {}
        target = target[key]

    # Set the value
    target[keys[-1]] = value
    save_context(ctx)

    return {"updated": True, "field": field_path, "value": value}


def get_context() -> dict:
    """Return the full startup context (for MCP stats tool)."""
    return load_context()


def get_decisions() -> dict:
    """Return the full decision log."""
    return load_decisions()


# ════════════════════════════════════════════════════════════════
#  TERMINAL INTERFACE
# ════════════════════════════════════════════════════════════════

def _print_divider():
    print("\n" + "━" * 60 + "\n")


def _terminal():
    print("""
╔══════════════════════════════════════════════════════════════╗
║   🤝  HORMOZI COFOUNDER — Terminal                          ║
║   Your AI business cofounder. Daily. Direct. Cited.         ║
╠══════════════════════════════════════════════════════════════╣
║   Commands:                                                  ║
║     brief         → morning audit (no question needed)      ║
║     log           → log a new decision                      ║
║     update        → update startup context                  ║
║     context       → show current startup state              ║
║     decisions     → show decision log                       ║
║     exit          → close                                   ║
╚══════════════════════════════════════════════════════════════╝
""")

    # Auto morning briefing on start
    print("  ⟳ Loading morning briefing...\n")
    try:
        briefing = daily_briefing()
        _print_divider()
        print(f"📋 DAILY BRIEFING — {briefing['date']}\n")
        print(briefing["briefing"])
        _print_divider()
    except Exception as e:
        print(f"  ⚠ Briefing failed: {e}\n")

    while True:
        try:
            print("You: ", end="")
            user_input = input().strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Stay hard.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("\n  Stay hard.")
            break

        if user_input.lower() == "brief":
            print("  ⟳ Running audit...\n")
            try:
                result = daily_briefing()
                _print_divider()
                print(f"📋 BRIEFING — {result['date']}\n")
                print(result["briefing"])
                _print_divider()
            except Exception as e:
                print(f"  ❌ {e}\n")
            continue

        if user_input.lower() == "context":
            ctx = load_context()
            _print_divider()
            print(format_context_block(ctx))
            _print_divider()
            continue

        if user_input.lower() == "decisions":
            log = load_decisions()
            _print_divider()
            print(format_decision_block(log, limit=20))
            _print_divider()
            continue

        if user_input.lower() == "update":
            print("  Field path (e.g. startup.name): ", end="")
            field = input().strip()
            print("  New value: ", end="")
            raw_val = input().strip()
            # Try to parse as JSON for lists/numbers
            try:
                value = json.loads(raw_val)
            except Exception:
                value = raw_val
            result = update_context(field, value)
            print(f"  ✓ Updated {result['field']} = {result['value']}\n")
            continue

        if user_input.lower() == "log":
            print("  Decision/question: ", end="")
            question = input().strip()
            print("  Options considered (comma separated): ", end="")
            options = [o.strip() for o in input().split(",")]
            print("  Hormozi's recommendation: ", end="")
            rec = input().strip()
            print("  What you decided: ", end="")
            decided = input().strip()
            print("  Category (strategy/product/market/hiring/finance): ", end="")
            cat = input().strip() or "strategy"
            result = log_decision(question, options, rec, decided, category=cat)
            print(f"  ✓ Decision #{result['decision_id']} logged.\n")
            continue

        # Default: ask cofounder
        print("  ⟳ Thinking...\n")
        try:
            result = ask_cofounder(user_input)
            _print_divider()
            print("Hormozi (Cofounder):\n")
            print(result["answer"])
            _print_divider()
        except Exception as e:
            print(f"  ❌ {e}\n")


if __name__ == "__main__":
    _terminal()