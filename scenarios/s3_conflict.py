"""Scenario 3: conflict resolution. A stored memory says a fix worked. A newer closed case says it did not.

Part A  LIBRARY DEFAULT: let the library's own LLM decide add / update / delete. We only OBSERVE what it did.
        (LLM output can vary from run to run. We report what happened, we do not promise it.)
Part B  NINEONE GUARD: the same change goes through the guard. It waits for an SME, then the old memory is
        soft-deleted (kept in history) and the new one goes live.

Part A uses 1 chat call per backend. Part B uses embeddings only.
Run:  python -m scenarios.s3_conflict --backend both
"""
from __future__ import annotations

from datetime import datetime, timezone

from nineone_mem.memory.base import Scope
from nineone_mem.memory.guard import Candidate, MemoryGuard

from .common import banner, calls, make_backend, new_tenant, parse_backends, short, sub

SITE, CELL = "TOK-104", "RNA1301000057_1"
OLD = f"A 2 degree tilt change worked on cell {CELL}."
NEW_FACT = f"Update from the latest closed case: the 2 degree tilt change on cell {CELL} did NOT work. Accessibility fell again within a day."
TOPIC = f"tilt_outcome:{CELL}"


def part_a_library_default(name: str) -> dict:
    b = make_backend(name)
    scope = Scope("site", tenant=new_tenant("s3a"), site_id=SITE, cell_id=CELL)
    old = b.add(OLD, scope)
    events = b.extract([{"role": "user", "content": NEW_FACT}], scope)
    live = [r.content for r in b.list(scope)]
    hist = b.history(old.id)
    old_text_gone = OLD not in live
    out = {
        "events": [(e["event"], short(e["after"] or e["before"], 70)) for e in events],
        "live_after": live,
        "old_still_live": not old_text_gone,
        "old_text_recoverable": (not old_text_gone) or any(OLD in str(h) for h in hist),
        "library_history_entries": len(hist),
        # Two live memories that disagree = the agent can be shown both "worked" and "did not work".
        "contradiction_left_live": (not old_text_gone) and len(live) > 1,
    }
    b.close()
    return out


def part_b_guard(name: str) -> dict:
    b = make_backend(name)
    g = MemoryGuard(b)
    tenant = new_tenant("s3b")
    scope = Scope("site", tenant=tenant, site_id=SITE, cell_id=CELL)

    def cand(text, sources):
        return Candidate(text, scope, "precedent", "consolidator", sources, TOPIC)

    first = g.propose(cand("The 2 degree tilt change on this cell worked in the first closed case.", ["C-TOK104-00"]))
    before_change = datetime.now(timezone.utc)
    second = g.propose(cand("The 2 degree tilt change on this cell did not hold in the latest closed case.", ["C-TOK104-08"]))
    live_while_pending = [r.content for r in b.list(scope)]
    approved = g.approve(second.candidate_id, "sme")
    live_after = [r.content for r in b.list(scope)]
    out = {
        "first": first.status, "second": second.status, "conflicts_with_first": second.conflicts_with == first.memory_id,
        "live_while_pending": live_while_pending, "approved": approved.status, "live_after_approval": live_after,
        "as_of_before_change": [m["content"] for m in g.as_of(scope, before_change)],
        "as_of_now": [m["content"] for m in g.as_of(scope, datetime.now(timezone.utc))],
        # Who else tries to write? The RCA agent must not (v3: one writer).
        "rca_write_refused": g.propose(Candidate("RCA says tilt works.", scope, "precedent", "RAN_A8_rca", ["C-TOK104-00"])).status,
        # An SME correction (v3 memory #7) comes in through its own owner, at global scope, with a review id.
        "sme_correction": g.propose(Candidate(
            "SME correction: on macro urban cells a tilt change is not the usual fix; check authorisation first.",
            Scope("global", tenant=tenant), "sme_correction", "sme_feedback", ["sme_review:demo-1"])).status,
    }
    b.close()
    return out


def run(name: str) -> dict:
    return {"backend": name, "a": part_a_library_default(name), "b": part_b_guard(name)}


def report(res: dict) -> None:
    a, b = res["a"], res["b"]
    sub(f"{res['backend'].upper()}  Part A: the library decides on its own")
    print(f"  events: {a['events']}")
    for t in a["live_after"]:
        print(f"  live memory: {short(t)}")
    print(f"  old text still live: {a['old_still_live']}   old text recoverable at all: {a['old_text_recoverable']}"
          f"   library history entries: {a['library_history_entries']}")
    print(f"  contradiction left live: {a['contradiction_left_live']}")
    sub(f"{res['backend'].upper()}  Part B: through the NineOne guard")
    print(f"  first memory: {b['first']} | second (same topic, different text): {b['second']}")
    print(f"  live while waiting for SME: {[short(t, 60) for t in b['live_while_pending']]}")
    print(f"  SME approves -> {b['approved']}; live now: {[short(t, 60) for t in b['live_after_approval']]}")
    print(f"  as-of BEFORE the change: {[short(t, 60) for t in b['as_of_before_change']]}")
    print(f"  as-of NOW:               {[short(t, 60) for t in b['as_of_now']]}")
    print(f"  RCA agent tries to write memory -> {b['rca_write_refused']}; SME correction via its owner -> {b['sme_correction']}")


def main(argv=None) -> None:
    banner("SCENARIO 3: conflict resolution")
    for name in parse_backends("Scenario 3", argv):
        report(run(name))
    print("\n" + calls())


if __name__ == "__main__":
    main()
