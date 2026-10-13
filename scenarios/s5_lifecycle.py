"""Scenario 5: the life of a memory. Writing it, removing it, and replaying an old case.

1) HOT PATH write: the library's own LLM saves a memory WHILE the run is happening.
   We time it. The engineer would be waiting for that. The memory is live at once, with no source and no review.
2) BACKGROUND write (the NineOne way): nothing is saved during the answer. After the case closes the
   consolidator proposes memories from the ledger. Zero chat calls, and every one goes through the guard.
3) SOFT DELETE and REPLAY (v3 MI-6 / MI-7): a case remembers which memory versions it saw. After the
   memory changes, we rebuild exactly what that case saw from history.

Uses 1 chat call per backend (the hot-path write). Run:  python -m scenarios.s5_lifecycle --backend both
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

import psycopg

from nineone_mem import config
from nineone_mem.agent.build import RECALL_QUERY
from nineone_mem.agent.context import RunContext
from nineone_mem.agent.tools import recall
from nineone_mem.consolidate import build_precedent_candidates, consolidate
from nineone_mem.llm import COUNTER
from nineone_mem.memory.base import Scope
from nineone_mem.memory.guard import MemoryGuard

from .common import banner, calls, make_backend, new_tenant, parse_backends, short, sub

SITE, CELL = "TOK-104", "RNA1301000057_1"


def run(name: str) -> dict:
    b = make_backend(name)
    g, tenant = MemoryGuard(b), new_tenant("s5")
    cell_scope = Scope("site", tenant=tenant, site_id=SITE, cell_id=CELL)
    site_scope = Scope("sitewide", tenant=tenant, site_id=SITE)

    # ---- 1) hot path
    t0 = time.time()
    events = b.extract([{"role": "user", "content": f"Closed case: reverting the tilt change on {CELL} held."}], cell_scope)
    hot_secs = round(time.time() - t0, 1)
    hot_records = b.list(cell_scope)
    hot = {"seconds_added_to_the_answer": hot_secs, "events": [e["event"] for e in events],
           "memory": [r.content for r in hot_records],
           "has_source": any("sources" in r.metadata for r in hot_records), "reviewed_by_anyone": False}

    # ---- 2) background write
    chat_before, t1 = COUNTER.chat_calls, time.time()
    decisions = consolidate(g, tenant=tenant, only_site=SITE)
    bg = {"seconds": round(time.time() - t1, 2), "chat_calls": COUNTER.chat_calls - chat_before,
          "decisions": [d.status for d in decisions], "memory": [r.content for r in b.list(site_scope)],
          "has_source": all("sources" in r.metadata for r in b.list(site_scope))}

    # ---- 3) soft delete + replay
    ctx = RunContext(backend=b, run_id="case-A", site_id=SITE, cell_id=CELL, window="-", tenant=tenant)
    recall(ctx, RECALL_QUERY)                                           # what the case saw
    saw = sorted(m["content"] for m in ctx.retrieved_memories if m["scope"].split("/")[1] == "sitewide")
    t_case = datetime.now(timezone.utc)

    cand = next(c for c in build_precedent_candidates(tenant) if c.scope.site_id == SITE)
    cand.content = cand.content.replace("7 of 9", "7 of 10")             # the world moved on
    change = g.propose(cand)
    g.approve(change.candidate_id, "sme")
    old_key = change.conflicts_with
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute("SELECT version, event, active FROM ran.memory_history WHERE backend=%s AND memory_key=%s"
                            " ORDER BY version", (name, old_key)).fetchall()
    replay = sorted(m["content"] for m in g.as_of(site_scope, t_case))
    life = {"history_rows_for_old_memory": [(f"v{v}", e, "active" if a else "inactive") for v, e, a in rows],
            "live_now": [r.content for r in b.list(site_scope)],
            "case_saw": saw, "replay_from_history": replay, "replay_matches_what_case_saw": saw == replay}
    b.close()
    return {"backend": name, "hot": hot, "background": bg, "life": life}


def report(r: dict) -> None:
    h, bg, life = r["hot"], r["background"], r["life"]
    sub(r["backend"].upper())
    print("  1) HOT PATH (library LLM writes during the run)")
    print(f"     extra seconds the engineer waits: {h['seconds_added_to_the_answer']}   events: {h['events']}")
    print(f"     saved: {short(h['memory'][0] if h['memory'] else '-')}")
    print(f"     has a source: {h['has_source']}   reviewed by anyone: {h['reviewed_by_anyone']}   (live immediately)")
    print("  2) BACKGROUND (NineOne: consolidator after the case closes)")
    print(f"     chat calls: {bg['chat_calls']}   seconds: {bg['seconds']}   guard decisions: {bg['decisions']}")
    print(f"     saved: {short(bg['memory'][0] if bg['memory'] else '-')}   has sources: {bg['has_source']}")
    print("  3) SOFT DELETE + REPLAY")
    print(f"     old memory in history: {life['history_rows_for_old_memory']}")
    print(f"     live now: {[short(t, 125) for t in life['live_now']]}")
    print(f"     what the old case saw:  {[short(t, 125) for t in life['case_saw']]}")
    print(f"     rebuilt from history:   {[short(t, 125) for t in life['replay_from_history']]}")
    print(f"     replay matches what the case saw: {life['replay_matches_what_case_saw']}")


def main(argv=None) -> None:
    banner("SCENARIO 5: insert, delete and replay")
    for name in parse_backends("Scenario 5", argv):
        report(run(name))
    print("\n" + calls())


if __name__ == "__main__":
    main()
