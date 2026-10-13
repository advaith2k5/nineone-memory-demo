"""Scenario 6: whose memory is it? Agent-level, site-wide, global and role memory, and who may read or write each.

Part 1  Who can WRITE what: every writer tries every kind of memory (the guard's one-owner rule, v3 section 1).
Part 2  Who can READ what: the RCA agent and the Intake agent each search with their own scopes.
Part 3  Two v3 combination rules, enforced in code:
        Rule 1  a track record can reorder suspects but can never add or clear one
        Rule 2  two findings count as two opinions only if they read different sources

Uses embeddings only (no chat calls).   Run:  python -m scenarios.s6_multi_agent --backend both
"""
from __future__ import annotations

import uuid

from nineone_mem.agent.build import RECALL_QUERY
from nineone_mem.agent.context import RunContext
from nineone_mem.agent.tools import make_tools, recall
from nineone_mem.memory.base import Scope
from nineone_mem.memory.guard import Candidate, MemoryGuard
from nineone_mem.stubs.common import write_finding
from nineone_mem.stubs.upstream_agents import run_upstream_agents

from .common import banner, make_backend, new_tenant, parse_backends, short, sub

SITE, CELL = "TOK-104", "RNA1301000057_1"
WRITERS = ["consolidator", "sme_feedback", "admin", "RAN_A1_intake", "RAN_A8_rca", "RAN_A3_config"]


def _kinds(tenant: str, run_id: str):
    # (kind, scope it lives in, text, sources)
    return {
        "precedent": (Scope("sitewide", tenant=tenant, site_id=SITE), "On site TOK-104 a tilt revert held in 7 of 9 closed cases.", ["C-TOK104-00"]),
        "sme_correction": (Scope("global", tenant=tenant), "SME correction: check that a change was authorised before reverting it.", ["sme_review:demo-1"]),
        "role_preference": (Scope("role", tenant=tenant, role="noc_l2"), "NOC L2 engineers want a short summary first.", ["admin_request:demo-2"]),
        "agent_tag": (Scope("agent", tenant=tenant, agent_id="RAN_A1_intake"), f"Cell {CELL} was tagged repeat offender.", [run_id]),
    }


def part_write(name: str, run_id: str) -> dict:
    grid = {}
    for writer in WRITERS:
        grid[writer] = {}
        for kind in ("precedent", "sme_correction", "role_preference", "agent_tag"):
            b = make_backend(name)                                       # fresh tenant each time: no duplicates
            scope, text, sources = _kinds(new_tenant("s6w"), run_id)[kind]
            grid[writer][kind] = MemoryGuard(b).propose(Candidate(text, scope, kind, writer, sources)).status
            b.close()
    return grid


def part_read(name: str, run_id: str) -> dict:
    b, tenant = make_backend(name), new_tenant("s6r")
    g = MemoryGuard(b)
    for kind, (scope, text, sources) in _kinds(tenant, run_id).items():
        owner = {"precedent": "consolidator", "sme_correction": "sme_feedback", "role_preference": "admin", "agent_tag": "RAN_A1_intake"}[kind]
        g.propose(Candidate(text, scope, kind, owner, sources))
    rca = RunContext(backend=b, run_id=run_id, site_id=SITE, cell_id=CELL, window="-", tenant=tenant)
    seen_by_rca = recall(rca, RECALL_QUERY)
    # The Intake agent reads its OWN agent scope plus global. It is not given the RCA's cell/site scopes.
    intake_scopes = [Scope("agent", tenant=tenant, agent_id="RAN_A1_intake"), Scope("global", tenant=tenant)]
    seen_by_intake = [h.content for s in intake_scopes for h in b.search(RECALL_QUERY, s, limit=3)]
    out = {
        "rca_sees_site_precedent": "7 of 9" in seen_by_rca,
        "rca_sees_global_sme_correction": "authorised before reverting" in seen_by_rca,
        "rca_sees_intakes_private_tag": "repeat offender" in seen_by_rca,
        "rca_sees_role_preference": "short summary" in seen_by_rca,
        "intake_sees_its_own_tag": any("repeat offender" in t for t in seen_by_intake),
        "intake_sees_global_sme_correction": any("authorised before reverting" in t for t in seen_by_intake),
        "intake_sees_site_precedent": any("7 of 9" in t for t in seen_by_intake),
    }
    b.close()
    return out


def part_rules(name: str) -> dict:
    b = make_backend(name)
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    ctx = RunContext(backend=b, run_id=run_id, site_id=SITE, cell_id=CELL, window="-", tenant=new_tenant("s6c"))
    # Rule 1: only a config finding exists. A strong track record for 'fault' cannot make fault a suspect.
    write_finding("RAN_A3_config", run_id, SITE, CELL, "unauthorised_change_before_onset", "config_change", ["cm_change"], "tilt changed")
    tools = {t.name: t for t in make_tools(ctx)}
    tools["get_case_facts"].invoke({})   # the agent must read the facts first; this fills ctx.seen_finding_ids
    f_cfg = next(k for k in ctx.seen_finding_ids)
    rule1 = tools["emit_verdict"].invoke({"category": "fault", "evidence_for": [f_cfg], "reason": "fault track record is strong"})
    # Rule 2: two findings, same source -> one opinion (medium). Different sources -> two (high).
    def confidence(sources_a, sources_b):
        rid = f"run_{uuid.uuid4().hex[:8]}"
        c = RunContext(backend=b, run_id=rid, site_id=SITE, cell_id=CELL, window="-", tenant=new_tenant("s6c"))
        write_finding("RAN_A5_coverage", rid, SITE, CELL, "overshooter", "coverage", sources_a, "overshooting")
        write_finding("RAN_PERF_performance", rid, SITE, CELL, "poor_footprint", "coverage", sources_b, "poor footprint")
        t = {x.name: x for x in make_tools(c)}
        t["get_case_facts"].invoke({})
        t["emit_verdict"].invoke({"category": "coverage", "evidence_for": sorted(c.seen_finding_ids), "reason": "two coverage findings"})
        return c.verdict["confidence"]
    out = {"rule1_reply": rule1, "same_source_confidence": confidence(["mr_bins"], ["mr_bins"]),
           "different_sources_confidence": confidence(["mr_bins"], ["drive_test"])}
    b.close()
    return out


def run(name: str) -> dict:
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    run_upstream_agents(run_id, SITE, CELL)      # a real case record, so 'agent_tag' can cite it as a source
    return {"backend": name, "write": part_write(name, run_id), "read": part_read(name, run_id), "rules": part_rules(name)}


def report(r: dict) -> None:
    sub(r["backend"].upper())
    kinds = ["precedent", "sme_correction", "role_preference", "agent_tag"]
    print("  1) who may WRITE what (stored = allowed, rejected = not the owner)")
    print(f"     {'writer':16s} " + " ".join(f"{k:16s}" for k in kinds))
    for w, row in r["write"].items():
        print(f"     {w:16s} " + " ".join(f"{row[k]:16s}" for k in kinds))
    print("  2) who can READ what")
    for k, v in r["read"].items():
        print(f"     {k:36s} {v}")
    print("  3) combination rules (v3 section 5)")
    print(f"     Rule 1 (track record cannot add a suspect): {short(r['rules']['rule1_reply'], 110)}")
    print(f"     Rule 2 (same source -> {r['rules']['same_source_confidence']}, different sources -> {r['rules']['different_sources_confidence']})")


def main(argv=None) -> None:
    banner("SCENARIO 6: scope and ownership across agents")
    for name in parse_backends("Scenario 6", argv):
        report(run(name))


if __name__ == "__main__":
    main()
