"""Quick vault graph diagnostics."""
from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VAULT_DIR = ROOT / "hormozi-brain"

_spec = importlib.util.spec_from_file_location("viz", ROOT / "backend" / "viz.py")
assert _spec and _spec.loader
viz = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(viz)

build_full_vault_graph = viz.build_full_vault_graph
build_vault_index = viz.build_vault_index
extract_wikilinks = viz.extract_wikilinks
resolve_link = viz.resolve_link

vault = Path(VAULT_DIR)
g = build_full_vault_graph(vault)
idx = build_vault_index(vault)

total_links = 0
unresolved: list[str] = []
for path in vault.rglob("*.md"):
    for t in extract_wikilinks(path):
        total_links += 1
        if not resolve_link(t, idx):
            unresolved.append(t)

deg = Counter()
for e in g["edges"]:
    deg[e["from"]] += 1
    deg[e["to"]] += 1

orphans = sum(1 for n in g["nodes"] if deg[n["id"]] == 0)
print("nodes", len(g["nodes"]))
print("edges", len(g["edges"]))
print("total_wikilinks_in_files", total_links)
print("unresolved_wikilinks", len(unresolved))
print("unique_unresolved", len(set(unresolved)))
print("orphan_nodes", orphans)
print("max_degree", max(deg.values()) if deg else 0)
print("top_hubs", deg.most_common(10))
samples = [s.encode("ascii", "backslashreplace").decode() for s in list(dict.fromkeys(unresolved))[:25]]
print("sample_unresolved", samples)

# categorize unresolved
import re
heading = sum(1 for u in unresolved if "#" in u)
block = sum(1 for u in unresolved if "^" in u)
folder = sum(1 for u in unresolved if u.endswith("/"))
bare = sum(1 for u in unresolved if "/" not in u)
print("unresolved_with_heading", heading)
print("unresolved_with_block", block)
print("unresolved_folder_links", folder)
print("unresolved_bare_names", bare)

missing_notes = 0
index_miss = 0
for u in set(unresolved):
    norm = viz.normalize_wikilink_target(u)
    if not norm:
        continue
    if viz.resolve_link(norm, idx):
        index_miss += 1
    else:
        missing_notes += 1
print("unresolved_missing_note_files", missing_notes)
print("unresolved_index_lookup_failures", index_miss)
