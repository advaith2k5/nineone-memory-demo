"""Fake network data. Run once (safe to re-run, it wipes and refills the mock tables).

    python -m nineone_mem.seed.mock_data

Everything here is invented, but the numbers follow Saurabh's v3 doc so the demo
lines up with it:
- worked case: cell RNA1301000057_1, accessibility 96.0% vs target 99.0%, 08:00-11:00 (v3 section 5)
- track record: 86 cases, precision 0.72 (v3 section 6.3 example JSON)
- "this revert held in 7 of 9 similar cases here" (v3 memory #6)

Two kinds of data are written, and they are NOT memory:
- mock.* tables = "today's numbers" (PM / FM / CM feeds), read by the get_case_facts tool
- ledger.outcomes = the outcome ledger. In real life ONLY RAN_A9 (Action Watcher) writes it.
  Here this seed script plays the role of A9 for history that already happened.
"""
from datetime import datetime, timedelta, timezone

import psycopg

from .. import config

UTC = timezone.utc
CASE_DAY = datetime(2026, 10, 12, tzinfo=UTC)

# Same site on purpose: filtering by site alone cannot tell these two cells apart,
# only the exact cell id can. That is the point of scenario 2.
CELLS = {
    "RNA1301000057_1": {"site": "TOK-104"},   # the cell in trouble
    "RNA1301000058_1": {"site": "TOK-104"},   # look-alike neighbour, healthy
    "RNA1301000060_1": {"site": "TOK-105"},
}
CELL_CLASS = {"site_type": "macro", "clutter": "urban", "band": "1.7GHz"}
FINDING = "unauthorised_change_before_onset"


def _pm_rows():
    s, e = CASE_DAY.replace(hour=8), CASE_DAY.replace(hour=11)
    return [
        ("RNA1301000057_1", "accessibility", s, e, 96.0, 99.0),   # bad
        ("RNA1301000058_1", "accessibility", s, e, 99.4, 99.0),   # fine
        ("RNA1301000060_1", "accessibility", s, e, 99.1, 99.0),   # fine
    ]


def _fm_rows():
    # A MINOR alarm that is not service-affecting (v3 memory #5: weighted down).
    return [("RNA1301000057_1", "FAN SPEED LOW", "MINOR", CASE_DAY.replace(hour=2), None)]


def _cm_rows():
    return [("RNA1301000057_1", "electrical_tilt", "4", "6", CASE_DAY.replace(hour=2), False)]


def _ledger_rows():
    """86 closed cases of one finding type; 62 held (0.72). 9 are on TOK-104 and 7 of those held."""
    rows = []
    start = datetime(2026, 4, 1, tzinfo=UTC)
    # 9 cases on site TOK-104: revert held 7 times.
    for i in range(9):
        rows.append((f"C-TOK104-{i:02d}", "TOK-104", f"RNA13010000{50 + i}_1", FINDING,
                     "revert_tilt_change", i < 7, start + timedelta(days=10 * i)))
    # 77 other cases elsewhere: 55 held, 22 did not (62 total held of 86).
    for i in range(77):
        rows.append((f"C-OTHER-{i:03d}", f"TOK-2{i % 9:02d}", f"RNA13020000{i:02d}_1", FINDING,
                     "revert_tilt_change", i < 55, start + timedelta(days=2 * i)))
    # A thin record for the "under 30 samples" demo: 4 cases, all held (looks perfect, means little).
    for i in range(4):
        rows.append((f"C-THIN-{i}", "TOK-300", f"RNA13030000{i}_1", "alarm_signature_baseband",
                     "replace_baseband_board", True, start + timedelta(days=20 * i)))
    return rows


def seed() -> dict:
    with psycopg.connect(config.DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute("TRUNCATE mock.pm_kpi, mock.fm_alarm, mock.cm_change, ledger.outcomes RESTART IDENTITY")
        cur.executemany("INSERT INTO mock.pm_kpi VALUES (%s,%s,%s,%s,%s,%s)", _pm_rows())
        cur.executemany("INSERT INTO mock.fm_alarm VALUES (%s,%s,%s,%s,%s)", _fm_rows())
        cur.executemany("INSERT INTO mock.cm_change VALUES (%s,%s,%s,%s,%s,%s)", _cm_rows())
        for case_id, site, cell, ftype, action, held, at in _ledger_rows():
            cell_class = CELL_CLASS if ftype == FINDING else {**CELL_CLASS, "site_type": "indoor"}
            cur.execute(
                "INSERT INTO ledger.outcomes (case_id, site_id, cell_id, finding_type, cell_class,"
                " action_taken, held, observed_at) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s)",
                (case_id, site, cell, ftype, psycopg.types.json.Jsonb(cell_class), action, held, at),
            )
        conn.commit()
        cur.execute("SELECT finding_type, count(*), count(*) FILTER (WHERE held) FROM ledger.outcomes GROUP BY 1")
        return {r[0]: (r[1], r[2]) for r in cur.fetchall()}


if __name__ == "__main__":
    print("Ledger (finding_type: total, held):", seed())
