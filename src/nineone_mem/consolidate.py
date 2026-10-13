"""The background job that turns closed cases into memories. Meant to run after cases close (nightly),
NEVER while an engineer is waiting for an answer (HLD slide 2).

No LLM is used here. The numbers are counted by SQL and the sentence is filled from a fixed
template, so a memory can never contain a number the ledger does not back up (HLD: "worked 20 of
24 is counted by SQL, never by the LLM"; v3 section 2: tracking records are counting, not a model).

Each result goes through the guard like any other candidate. If a count has changed since the last
run, the guard sees the same topic with new text and sends it to the SME queue, it does not
overwrite silently.
"""
from __future__ import annotations

import psycopg

from . import config
from .memory.base import Scope
from .memory.guard import Candidate, Decision, MemoryGuard

MIN_CASES = 3   # fewer closed cases than this is not worth a memory


def build_precedent_candidates(tenant: str = config.TENANT) -> list[Candidate]:
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute(
            "SELECT site_id, finding_type, action_taken, count(*), count(*) FILTER (WHERE held),"
            " min(observed_at)::date, max(observed_at)::date, array_agg(case_id ORDER BY case_id)"
            " FROM ledger.outcomes GROUP BY site_id, finding_type, action_taken HAVING count(*) >= %s"
            " ORDER BY site_id, finding_type", (MIN_CASES,)).fetchall()
    out = []
    for site, ftype, action, n, held, first, last, case_ids in rows:
        text = (f"On site {site}, '{action}' after '{ftype}' held in {held} of {n} closed cases "
                f"({first} to {last}).")
        out.append(Candidate(content=text, scope=Scope("sitewide", tenant=tenant, site_id=site), kind="precedent",
                             writer="consolidator", sources=list(case_ids), topic=f"precedent:{site}:{ftype}:{action}"))
    return out


def consolidate(guard: MemoryGuard, tenant: str = config.TENANT, only_site: str | None = None) -> list[Decision]:
    decisions = []
    for cand in build_precedent_candidates(tenant):
        if only_site and cand.scope.site_id != only_site:
            continue
        decisions.append(guard.propose(cand))
    return decisions
