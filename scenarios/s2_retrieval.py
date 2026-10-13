"""Scenario 2: retrieval. Why searching by meaning alone can hand the agent the WRONG cell's history.

Two cells sit on the same site. Their IDs differ by one digit and their memories read almost the same.
We ask the same questions two ways:
  A) search the whole site by meaning (no cell filter)
  B) search inside this exact cell (filter first, then rank by meaning)

Uses embeddings only. No chat calls.   Run:  python -m scenarios.s2_retrieval --backend both
"""
from __future__ import annotations

import re

from nineone_mem.memory.base import Scope

from .common import banner, make_backend, new_tenant, parse_backends, short, sub

SITE = "TOK-104"
CELL_A, CELL_B = "RNA1301000057_1", "RNA1301000058_1"
MEMORIES = {
    CELL_A: f"Accessibility drop on {CELL_A} was caused by an unauthorised tilt change. Reverting the change held.",
    CELL_B: f"Accessibility drop on {CELL_B} was caused by a failed baseband board. Replacing the board held.",
}
# (target cell, kind of query, query text)
QUERIES = [
    (CELL_A, "mentions the cell id", f"what caused the accessibility drop on {CELL_A}?"),
    (CELL_B, "mentions the cell id", f"what caused the accessibility drop on {CELL_B}?"),
    # The agent usually asks without typing a cell id. Embeddings cannot know which cell it means.
    (CELL_A, "no cell id", "what caused the accessibility drop and what fixed it?"),
    (CELL_B, "no cell id", "what caused the accessibility drop and what fixed it?"),
]


def _cell_of(text: str) -> str:
    return re.search(r"RNA\d+_\d", text).group(0)


def run(backend_name: str) -> dict:
    b = make_backend(backend_name)
    tenant = new_tenant("s2")
    for cell, text in MEMORIES.items():
        b.add(text, Scope("site", tenant=tenant, site_id=SITE, cell_id=cell))
    whole_site = Scope("site", tenant=tenant, site_id=SITE)          # no cell = prefix search over all cells

    rows = []
    for target, kind, query in QUERIES:
        wide = b.search(query, whole_site, limit=2)
        exact = b.search(query, Scope("site", tenant=tenant, site_id=SITE, cell_id=target), limit=2)
        rows.append({
            "target": target, "kind": kind, "query": query,
            "wide_top1": _cell_of(wide[0].content), "wide_scores": {_cell_of(h.content): round(h.score, 3) for h in wide},
            "wide_correct": _cell_of(wide[0].content) == target,
            "exact_top1": _cell_of(exact[0].content), "exact_correct": _cell_of(exact[0].content) == target,
        })
    b.close()
    return {"backend": backend_name, "rows": rows,
            "wide_accuracy": sum(r["wide_correct"] for r in rows) / len(rows),
            "exact_accuracy": sum(r["exact_correct"] for r in rows) / len(rows)}


def report(res: dict) -> None:
    sub(f"{res['backend'].upper()}")
    print(f"  {'agent is working on':20s} {'query':22s} {'A) whole site -> top hit':26s} {'B) this cell only'}")
    for r in res["rows"]:
        a = f"{r['wide_top1'][-6:]} {'OK ' if r['wide_correct'] else 'WRONG CELL'}"
        bb = f"{r['exact_top1'][-6:]} {'OK' if r['exact_correct'] else 'WRONG'}"
        print(f"  {r['target']:20s} {r['kind']:22s} {a:26s} {bb}")
        print(f"      scores seen in A: {r['wide_scores']}   | query: {short(r['query'], 60)}")
    print(f"  accuracy  A) whole-site search: {res['wide_accuracy']:.0%}   B) filter by cell first: {res['exact_accuracy']:.0%}")


def main(argv=None) -> None:
    banner("SCENARIO 2: retrieval. Filter first, then rank by meaning")
    for name in parse_backends("Scenario 2", argv):
        report(run(name))
    print("\nWhy: an embedding turns text into numbers that capture MEANING. Two cell ids that differ by one\n"
          "digit mean almost the same thing, so ranking cannot tell them apart. The fix is not a better\n"
          "model: it is to cut the search down to the right cell (the namespace / metadata filter) first.")


if __name__ == "__main__":
    main()
