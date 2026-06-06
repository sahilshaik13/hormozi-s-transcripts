#!/usr/bin/env python3
"""Vercel build: compile Vite UI into public/ for CDN + SPA fallback."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
DIST = WEB / "dist"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    if not (ROOT / "hormozi-index").exists():
        print(
            "WARNING: hormozi-index/ not found. "
            "RAG endpoints will fail until the index is included in the deployment.",
            file=sys.stderr,
        )
    if not (ROOT / "hormozi-brain").exists():
        print(
            "WARNING: hormozi-brain/ not found. "
            "Graph and note endpoints will fail until the vault is included.",
            file=sys.stderr,
        )

    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    if not (WEB / "node_modules").is_dir():
        run([npm, "install", "--prefix", str(WEB)])
    run([npm, "run", "build", "--prefix", str(WEB)])

    if not DIST.is_dir():
        raise SystemExit(f"Vite build output missing: {DIST}")

    node = "node.exe" if sys.platform == "win32" else "node"
    run([node, str(ROOT / "scripts" / "copy-public.mjs")])



if __name__ == "__main__":
    main()
