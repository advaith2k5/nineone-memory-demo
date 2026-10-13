"""Offline tests (database only, no Gemini calls) for the stub agents."""
import uuid

import psycopg
import pytest

from nineone_mem import config
from nineone_mem.stubs.action_watcher import record_outcome
from nineone_mem.stubs.common import write_finding
from nineone_mem.stubs.upstream_agents import run_upstream_agents

SITE = "TOK-104"


def findings(run_id, cell):
    with psycopg.connect(config.DATABASE_URL) as conn:
        rows = conn.execute("SELECT agent, verdict, payload, written_by FROM ran.agent_evidence"
                            " WHERE pipeline_run_id=%s AND cell_id=%s", (run_id, cell)).fetchall()
    return {r[0]: r for r in rows}


def test_bad_cell_gets_the_expected_findings():
    run = f"run_{uuid.uuid4().hex[:8]}"
    run_upstream_agents(run, SITE, "RNA1301000057_1")
    f = findings(run, "RNA1301000057_1")
    assert f["RAN_A3_config"][1] == "unauthorised_change_before_onset" and f["RAN_A3_config"][2]["supports"] == "config_change"
    assert f["RAN_A2_fault"][1] == "minor_alarm_not_service_affecting" and f["RAN_A2_fault"][2]["weight"] == "low"
    assert "gap 3.0" in f["RAN_PERF_performance"][2]["detail"]          # 99.0 - 96.0, computed in code
    assert f["RAN_A5_coverage"][1] == "no_coverage_feed"
    for agent, (_, _, payload, written_by) in f.items():
        assert written_by == agent and payload["rule_id"].startswith(agent)   # one writer, every row has a rule id


def test_healthy_look_alike_cell_gets_no_cause():
    run = f"run_{uuid.uuid4().hex[:8]}"
    run_upstream_agents(run, SITE, "RNA1301000058_1")
    f = findings(run, "RNA1301000058_1")
    assert f["RAN_A1_intake"][1] == "not_a_worst_cell"
    assert all(v[2]["supports"] is None for v in f.values())


def test_cell_with_no_data_is_reported_as_missing_not_guessed():
    run = f"run_{uuid.uuid4().hex[:8]}"
    run_upstream_agents(run, "TOK-999", "RNA9999999999_1")
    f = findings(run, "RNA9999999999_1")
    assert f["RAN_PERF_performance"][1] == "no_kpi_data"


def test_a_supporting_finding_without_sources_is_refused():
    with pytest.raises(ValueError):
        write_finding("RAN_A3_config", "r", SITE, "c", "x", "config_change", [], "no sources")


def test_only_the_action_watcher_may_write_the_ledger():
    with pytest.raises(psycopg.errors.CheckViolation):
        record_outcome("X1", SITE, "c", "f", {}, "a", True, "2026-10-01", written_by="RAN_A8_rca")


def test_fault_agent_picks_the_most_severe_alarm_not_whichever_row_comes_first():
    cell = "RNA0000000001_1"
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute("INSERT INTO mock.fm_alarm VALUES (%s,'FAN SPEED LOW','MINOR',now(),NULL),"
                     "(%s,'BASEBAND FAILURE','MAJOR',now() - interval '1 hour',NULL)", (cell, cell))
    try:
        run = f"run_{uuid.uuid4().hex[:8]}"
        from nineone_mem.stubs.upstream_agents import run_fault
        run_fault(run, "TOK-999", cell)
        f = findings(run, cell)["RAN_A2_fault"]
        assert f[1] == "service_affecting_alarm" and f[2]["weight"] == "high"   # the MAJOR one, although older
    finally:
        with psycopg.connect(config.DATABASE_URL) as conn:
            conn.execute("DELETE FROM mock.fm_alarm WHERE cell_id=%s", (cell,))


def test_track_record_with_no_cases_is_neutral_even_if_the_floor_is_zero():
    from nineone_mem.stubs.action_watcher import track_record
    r = track_record("a_finding_type_with_no_cases", {"site_type": "macro"}, floor=0)    # used to divide by zero
    assert r["sample_size"] == 0 and r["status"] == "neutral" and r["precision"] is None
