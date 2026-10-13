"""End to end: one worst-cell case, then the next one starts smarter.

    seed memory (consolidator + SME) -> RUN 1 (Intake, Performance, Config, Fault, Coverage -> RCA)
    -> Action Watcher records that the fix did NOT hold -> consolidator proposes the changed count
    -> SME approves -> RUN 2 on the same cell sees the new memory -> compare what each run saw.

Uses about 8 chat calls per backend. The extra ledger row is deleted at the end, so the demo data is unchanged.
Run:  python -m scenarios.e2e_case --backend both
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import psycopg

from nineone_mem import config
from nineone_mem.agent.build import run_case, trace
from nineone_mem.agent.context import RunContext
from nineone_mem.consolidate import consolidate
from nineone_mem.memory.base import Scope
from nineone_mem.memory.guard import Candidate, MemoryGuard
from nineone_mem.stubs.action_watcher import record_outcome, track_record
from nineone_mem.stubs.upstream_agents import run_upstream_agents

from .common import banner, calls, make_backend, new_tenant, parse_backends, short, sub

SITE, CELL = "TOK-104", "RNA1301000057_1"
CLASS = {"site_type": "macro", "clutter": "urban", "band": "1.7GHz"}
FINDING = "unauthorised_change_before_onset"


def _one_run(b, tenant: str, label: str) -> dict:
    run_id = f"{label}_{uuid.uuid4().hex[:6]}"
    run_upstream_agents(run_id, SITE, CELL)
    ctx = RunContext(backend=b, run_id=run_id, site_id=SITE, cell_id=CELL, window="2026-10-12 08:00-11:00 UTC", tenant=tenant)
    out = run_case(ctx)
    v = out["verdict"] or {}
    return {"run_id": run_id, "trace": trace(out["messages"]), "verdict": v, "rejections": ctx.rejections,
            "skills_loaded": out["skills_loaded"],
            "memory_seen": [m["content"] for m in ctx.retrieved_memories],
            "memory_cited": [m["content"] for m in v.get("memory_versions", [])]}


def run(name: str) -> dict:
    b, tenant = make_backend(name), new_tenant("e2e")
    g = MemoryGuard(b)
    seeded = [d.status for d in consolidate(g, tenant=tenant, only_site=SITE)]
    g.propose(Candidate("SME correction: check that a change was authorised before reverting it.",
                        Scope("global", tenant=tenant), "sme_correction", "sme_feedback", ["sme_review:demo-1"]))

    run1 = _one_run(b, tenant, "e2e1")

    # RAN_A9 sees the fix did NOT hold and records it (the only writer of the ledger).
    case_id = f"C-E2E-{uuid.uuid4().hex[:6]}"
    record_outcome(case_id, SITE, CELL, FINDING, CLASS, "revert_tilt_change", False, datetime.now(timezone.utc))
    try:
        record_after = track_record(FINDING, CLASS)
        proposed = consolidate(g, tenant=tenant, only_site=SITE)
        pending = [d for d in proposed if d.status == "pending_sme"]
        approved = [g.approve(d.candidate_id, "sme").status for d in pending]
        run2 = _one_run(b, tenant, "e2e2")
    finally:
        with psycopg.connect(config.DATABASE_URL) as conn:       # leave the demo ledger exactly as it was
            conn.execute("DELETE FROM ledger.outcomes WHERE case_id=%s", (case_id,))
    b.close()
    return {"backend": name, "seeded": seeded, "run1": run1, "ledger_after": record_after,
            "proposed": [d.status for d in proposed], "approved": approved, "run2": run2}


def _matching(texts, needle):  # the memory texts (shortened) that contain `needle`
    return [short(t, 120) for t in texts if needle in t]


def report(r: dict) -> None:
    sub(r["backend"].upper())
    for label, key in (("RUN 1", "run1"), ("RUN 2 (after the fix failed and the SME approved the new count)", "run2")):
        x = r[key]
        print(f"  {label}")
        print(x["trace"])
        print(f"     memory the agent was shown: {[short(t, 100) for t in x['memory_seen']]}")
        print(f"     verdict: {x['verdict'].get('category')}  confidence={x['verdict'].get('confidence')}  gate={x['verdict'].get('gate')}"
              f"  memories cited={len(x['memory_cited'])}  rejections={x['rejections'] or 'none'}")
        print(f"     skills loaded into prompt: {x['skills_loaded']}")
        print(f"     reason: {short(x['verdict'].get('reason', ''), 160)}")
    print(f"  seeded: {r['seeded']}   ledger after the failed fix: {r['ledger_after']['sample_size']} cases, precision {r['ledger_after']['precision']}")
    print(f"  consolidator proposed: {r['proposed']}   SME: {r['approved']}")
    old = _matching(r["run1"]["memory_seen"], "7 of 9")
    new = _matching(r["run2"]["memory_seen"], "7 of 10")
    print(f"  run 1 saw the old count ('7 of 9'): {bool(old)}   run 2 saw the new count ('7 of 10'): {bool(new)}")


def main(argv=None) -> None:
    banner("END TO END: a case, a failed fix, and a smarter next case")
    for name in parse_backends("End to end", argv):
        report(run(name))
    print("\n" + calls())


if __name__ == "__main__":
    main()
