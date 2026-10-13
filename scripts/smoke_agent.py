"""One live run of the RCA agent, with hand-made findings and 2 memories. Prints every step.

Gemini use: ~3-8 chat calls (the agent's own loop) + a few embeddings.
Run:  .venv/Scripts/python.exe scripts/smoke_agent.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from nineone_mem import config  # noqa: E402
from nineone_mem.agent.build import run_case, trace  # noqa: E402
from nineone_mem.agent.context import RunContext  # noqa: E402
from nineone_mem.llm import COUNTER  # noqa: E402
from nineone_mem.memory.base import Scope  # noqa: E402
from nineone_mem.memory.langmem_backend import LangMemBackend  # noqa: E402

SITE, CELL = "TOK-104", "RNA1301000057_1"


def add_finding(run_id, agent, finding_type, supports, sources, detail):
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO ran.agent_evidence (pipeline_run_id, site_id, cell_id, agent, verdict, gate, payload, written_by)"
            " VALUES (%s,%s,%s,%s,%s,'passed',%s,%s)",
            (run_id, SITE, CELL, agent, finding_type,
             Jsonb({"rule_id": "stub", "supports": supports, "sources": sources, "detail": detail}), agent),
        )


def main():
    backend = LangMemBackend()
    tenant = f"smoke_{uuid.uuid4().hex[:6]}"
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    mine = Scope("site", tenant=tenant, site_id=SITE, cell_id=CELL)
    backend.add("Reverting an unauthorised tilt change on this cell held in 7 of 9 similar cases.", mine)
    backend.add("Fan speed low alarms on this cell were cleared by a filter clean in March.", mine)

    add_finding(run_id, "RAN_A3_config", "unauthorised_change_before_onset", "config_change", ["cm_change"],
                "Electrical tilt changed 4 -> 6 at 02:00 UTC without authorisation, before the drop.")
    add_finding(run_id, "RAN_A2_fault", "minor_alarm_not_service_affecting", "fault", ["fm_alarm"],
                "MINOR alarm FAN SPEED LOW at 02:00 UTC. Not service-affecting.")

    ctx = RunContext(backend=backend, run_id=run_id, site_id=SITE, cell_id=CELL,
                     window="2026-10-12 08:00-11:00 UTC", tenant=tenant)
    out = run_case(ctx)
    print("\n--- WHAT THE AGENT DID ---")
    print(trace(out["messages"]))
    print("\n--- VERDICT (checked by code) ---")
    print(out["verdict"])
    print("\n--- REJECTIONS ---", ctx.rejections or "none")
    print("\n" + COUNTER.summary())
    backend.close()


if __name__ == "__main__":
    main()
