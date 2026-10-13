"""Shared helper: every stub agent leaves its finding in the case record through here.

The finding always carries rule_id, what it supports, and its sources. That is the
citation rule from the harness template: a claim with no source is not allowed.
The row is written under the agent's own name (one writer per row).
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from .. import config


def write_finding(agent: str, run_id: str, site_id: str, cell_id: str, finding_type: str,
                  supports: str | None, sources: list[str], detail: str, weight: str = "normal") -> None:
    if supports is not None and not sources:
        raise ValueError(f"{agent}: a finding that supports '{supports}' must name its sources")
    payload = {"rule_id": f"{agent}/demo-0.1", "supports": supports, "sources": sources,
               "detail": detail, "weight": weight}
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO ran.agent_evidence (pipeline_run_id, site_id, cell_id, agent, verdict, gate, payload, written_by)"
            " VALUES (%s,%s,%s,%s,%s,'passed',%s,%s)"
            " ON CONFLICT (pipeline_run_id, agent, site_id, cell_id)"
            " DO UPDATE SET verdict=EXCLUDED.verdict, payload=EXCLUDED.payload",
            (run_id, site_id, cell_id, agent, finding_type, Jsonb(payload), agent),
        )


def window_start(cell_id: str):
    """Start of the bad window for this cell, from the KPI feed. None if there is no KPI row."""
    with psycopg.connect(config.DATABASE_URL) as conn:
        row = conn.execute("SELECT min(window_start) FROM mock.pm_kpi WHERE cell_id=%s", (cell_id,)).fetchone()
    return row[0]
