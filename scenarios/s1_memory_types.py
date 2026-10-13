"""Scenario 1: memory vs skill vs system prompt. What is each piece of context, where does it live, who writes it.

Part 1  The map: every piece the RCA agent is given, labelled.
Part 2  The cache check: the part that is the same every run really is the same for two different cells.
Part 3  A real run, to see what the agent did with each piece (tool calls, was the skill opened,
        which memories were cited, is the short-term memory saved).

Uses about 4 chat calls per backend.   Run:  python -m scenarios.s1_memory_types --backend both
"""
from __future__ import annotations

import hashlib
import uuid

import psycopg

from nineone_mem import config
from nineone_mem.agent.build import HARNESS, facts_turn, run_case, trace
from nineone_mem.agent.context import RunContext
from nineone_mem.consolidate import consolidate
from nineone_mem.memory.base import Scope
from nineone_mem.memory.guard import Candidate, MemoryGuard
from nineone_mem.stubs.upstream_agents import run_upstream_agents

from .common import banner, calls, make_backend, new_tenant, parse_backends, sub

SITE, CELL = "TOK-104", "RNA1301000057_1"

# (piece, what kind of thing it is, where it lives, who changes it, how the agent gets it, same every run?)
MAP = [
    ("Who the agent is, hard bans", "SYSTEM PROMPT", "harness/rca/soul.md", "a person, by release", "always in the prompt", "yes (cached)"),
    ("Facts true for months, rulings, known gaps", "STATIC MEMORY", "harness/rca/AGENTS.md", "a person, by release", "always in the prompt", "yes (cached)"),
    ("How to do the task", "SKILL (procedural)", "harness/rca/skills/rca-categorise/SKILL.md", "a person, by release", "name + description at start, body when chosen", "yes"),
    ("This cell, this hour, today's numbers", "PER-RUN FACTS (not memory)", "mock PM / FM / CM tables", "the feeds", "get_case_facts tool + task message", "no"),
    ("Earlier cases, SME corrections", "LONG-TERM MEMORY (episodic)", "LangMem or Mem0 store in Postgres", "the guard only", "top-3 pre-loaded + search_memory", "no"),
    ("How often a finding type held", "TRACK RECORD (counted)", "ledger.outcomes, counted by SQL", "RAN_A9 only", "get_track_record tool", "no"),
    ("This run's scratchpad", "SHORT-TERM MEMORY", "PostgresSaver checkpoints", "the run itself", "automatic, keyed by run id", "no"),
]


def part_map() -> None:
    sub("1) THE MAP: what each piece is")
    print(f"  {'piece':44s} {'kind':28s} {'lives in':44s} {'who writes':22s} {'how the agent gets it'}")
    for piece, kind, home, writer, how, _ in MAP:
        print(f"  {piece:44s} {kind:28s} {home:44s} {writer:22s} {how}")


def part_cache(backend, tenant) -> dict:
    static = (HARNESS / "soul.md").read_text(encoding="utf-8") + (HARNESS / "AGENTS.md").read_text(encoding="utf-8")
    ctx_a = RunContext(backend=backend, run_id="a", site_id=SITE, cell_id="RNA1301000057_1", window="w", tenant=tenant)
    ctx_b = RunContext(backend=backend, run_id="b", site_id=SITE, cell_id="RNA1301000058_1", window="w", tenant=tenant)
    return {
        "static_prefix_sha": hashlib.sha256(static.encode()).hexdigest()[:12],
        "static_chars": len(static),
        "per_run_message_differs_between_cells": facts_turn(ctx_a) != facts_turn(ctx_b),
        "static_prefix_has_a_cell_id": "RNA13" in static,
    }


def part_run(name: str) -> dict:
    b = make_backend(name)
    tenant = new_tenant("s1")
    g = MemoryGuard(b)
    consolidate(g, tenant=tenant, only_site=SITE)                          # site precedent: "revert held in 7 of 9"
    g.propose(Candidate("SME correction: check that a change was authorised before reverting it.",
                        Scope("global", tenant=tenant), "sme_correction", "sme_feedback", ["sme_review:demo-1"]))
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    run_upstream_agents(run_id, SITE, CELL)
    ctx = RunContext(backend=b, run_id=run_id, site_id=SITE, cell_id=CELL, window="2026-10-12 08:00-11:00 UTC", tenant=tenant)
    cache = part_cache(b, tenant)
    out = run_case(ctx)
    msgs = out["messages"]
    called = [c["name"] for m in msgs if m.__class__.__name__ == "AIMessage" for c in m.tool_calls]
    with psycopg.connect(config.DATABASE_URL) as conn:
        checkpoints = conn.execute("SELECT count(*) FROM checkpoints WHERE thread_id=%s", (run_id,)).fetchone()[0]
    v = out["verdict"] or {}
    res = {
        "cache": cache, "tools_called": called, "trace": trace(msgs),
        "skill_body_opened": any(n == "read_file" for n in called),
        "skills_loaded_into_prompt": out["skills_loaded"],
        "recalled_before_model_started": len(ctx.retrieved_memories),
        "memories_cited": v.get("memories_used", []), "checkpoints_saved": checkpoints,
        "verdict": {k: v.get(k) for k in ("category", "confidence", "gate", "abstained")}, "rejections": ctx.rejections,
    }
    b.close()
    return res


def run(name: str) -> dict:
    return {"backend": name, **part_run(name)}


def report(r: dict) -> None:
    sub(r["backend"].upper() + "  (live run)")
    c = r["cache"]
    print(f"  2) cache check: static prefix = {c['static_chars']} chars, fingerprint {c['static_prefix_sha']}; "
          f"contains a cell id: {c['static_prefix_has_a_cell_id']}; per-run message differs between two cells: {c['per_run_message_differs_between_cells']}")
    print("  3) what the agent did:")
    print(r["trace"])
    print(f"     memories shown before the model started: {r['recalled_before_model_started']}   cited by the agent: {len(r['memories_cited'])}")
    print(f"     skills whose name+description were put in the prompt: {r['skills_loaded_into_prompt']}")
    print(f"     skill body opened (read_file called): {r['skill_body_opened']}   short-term checkpoints saved: {r['checkpoints_saved']}")
    print(f"     verdict: {r['verdict']}   rejections: {r['rejections'] or 'none'}")


def main(argv=None) -> None:
    banner("SCENARIO 1: memory vs skill vs system prompt")
    part_map()
    for name in parse_backends("Scenario 1", argv):
        report(run(name))
    print("\n" + calls())


if __name__ == "__main__":
    main()
