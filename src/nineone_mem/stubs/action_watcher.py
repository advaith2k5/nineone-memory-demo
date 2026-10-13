"""RAN_A9 Action Watcher (stub). The ONLY writer of the outcome ledger (v3 memory #6 and #14).

No AI here. A real A9 watches what happened after a change; this stub only has the two
jobs the demo needs:
  1. record_outcome(): write one closed case to ledger.outcomes
  2. track_record():   count the ledger and return the v3 section 6.3 "prior"

The count is plain SQL. A learned ranker would make it impossible to show an engineer why
one option sits above another (v3 section 2), and an LLM must never produce these numbers.
"""
from __future__ import annotations

import psycopg
from psycopg.types.json import Jsonb

from .. import config

WRITER = "RAN_A9_action_watcher"


def record_outcome(case_id: str, site_id: str, cell_id: str, finding_type: str, cell_class: dict,
                   action_taken: str, held: bool, observed_at, written_by: str = WRITER) -> None:
    """Add one closed case. The database itself refuses any writer other than A9."""
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute(
            "INSERT INTO ledger.outcomes (case_id, site_id, cell_id, finding_type, cell_class, action_taken,"
            " held, observed_at, written_by) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (case_id, site_id, cell_id, finding_type, Jsonb(cell_class), action_taken, held, observed_at, written_by),
        )


def track_record(finding_type: str, cell_class: dict, floor: int = config.SAMPLE_FLOOR) -> dict:
    """How often this kind of finding held, on this class of cell. Never about one cell.

    Below `floor` cases the precision is hidden and the record is marked neutral,
    because a record built on four cases is not a record (v3 section 6.3).
    """
    with psycopg.connect(config.DATABASE_URL) as conn:
        row = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE held), min(observed_at)::date, max(observed_at)::date"
            " FROM ledger.outcomes WHERE finding_type = %s AND cell_class = %s::jsonb",
            (finding_type, Jsonb(cell_class)),
        ).fetchone()
    total, held, first, last = row
    out = {
        "finding_type": finding_type,
        "cell_class": cell_class,
        "sample_size": total,
        "window": {"from": str(first) if first else None, "to": str(last) if last else None},
        "source": "ran_a9/ledger",
        "neutral_below_samples": floor,
    }
    # `total == 0` is checked on its own: with floor=0 the next branch would divide held by zero.
    if total == 0 or total < floor:
        out.update(precision=None, status="neutral",
                   note=f"only {total} cases, below the floor of {floor}; ignore this record")
    else:
        out.update(precision=round(held / total, 2), status="usable")
    return out
