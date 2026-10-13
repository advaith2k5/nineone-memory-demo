"""One test per scenario, on both backends. They run the real scenario code (the same thing the CLI prints).

What is asserted: things the CODE guarantees (ownership, counts, what was shown, what was refused).
What is NOT asserted: the exact words of an LLM. A model can phrase things differently run to run.

Chat calls: S1 ~8, S3 ~2, S5 ~2, E2E ~16. Everything else uses embeddings only.
Run one:  .venv/Scripts/python.exe -m pytest tests/test_scenarios.py -k s3 -v
"""
import pytest
import psycopg

from nineone_mem import config
from scenarios import e2e_case, s1_memory_types, s2_retrieval, s3_conflict, s4_garbage_in, s5_lifecycle, s6_multi_agent

BACKENDS = ["langmem", "mem0"]
CATEGORIES = {"config_change", "fault", "coverage", "capacity", "interference", "neighbour_impact", "external_event", "abstain"}


@pytest.fixture(scope="module", params=BACKENDS)
def name(request):
    return request.param


@pytest.mark.s1
@pytest.mark.live
def test_s1_memory_types(name):
    r = s1_memory_types.run(name)
    assert not r["cache"]["static_prefix_has_a_cell_id"] and r["cache"]["per_run_message_differs_between_cells"]
    assert "rca-categorise" in r["skills_loaded_into_prompt"]
    assert r["recalled_before_model_started"] == 2          # site precedent + SME correction, found by our code first
    assert r["checkpoints_saved"] > 0                        # short-term memory was written
    assert r["verdict"]["category"] in CATEGORIES and r["verdict"]["gate"] in ("passed", "awaiting_human")


@pytest.mark.s2
@pytest.mark.live
def test_s2_retrieval(name):
    r = s2_retrieval.run(name)
    assert r["exact_accuracy"] == 1.0                        # filter by cell first: always the right cell
    # Not luck: two of the four questions are the SAME generic text asked for two different cells, so a
    # whole-site search returns the same top hit for both and one of them is always the wrong cell.
    assert r["wide_accuracy"] < 1.0                          # similarity alone cannot tell two look-alike cells apart


@pytest.mark.s3
@pytest.mark.live
def test_s3_conflict(name):
    r = s3_conflict.run(name)
    a, b = r["a"], r["b"]
    assert a["live_after"]                                   # the library did something; we only observe what
    assert b["first"] == "stored" and b["second"] == "pending_sme" and b["conflicts_with_first"]
    assert len(b["live_while_pending"]) == 1 and "worked" in b["live_while_pending"][0]     # nothing changes before the SME
    assert b["approved"] == "approved" and "did not hold" in b["live_after_approval"][0]
    assert "worked" in b["as_of_before_change"][0] and "did not hold" in b["as_of_now"][0]  # old text kept, not lost
    assert b["rca_write_refused"] == "rejected" and b["sme_correction"] == "stored"


@pytest.mark.s4
@pytest.mark.live
def test_s4_garbage_in(name):
    r = s4_garbage_in.run(name)
    a, b, c, d = r["a"], r["b"], r["c"], r["d"]
    assert a["reaches_agent_without_guard"] and a["guard_no_source"][0] == "rejected"
    assert a["guard_fake_review_id"] == "stored"             # honest limit: the guard checks the id's shape, not that a review exists
    assert b["replaying_a_5_day_old_case_with_live_memory_sees_vcu_b"]       # live memory alone gives a wrong replay
    assert "vCU-A" in b["as_of_5_days_ago"][0] and "vCU-B" in b["as_of_now"][0]
    assert c["closing_tag_defanged"] and c["guard_status"] == "quarantined" and c["stored_after_guard"] == 0
    assert d["copies_shown_to_agent_without_guard"] >= 2     # duplicates crowd the 3 slots
    assert d["guard_statuses_for_5_repeats"] == ["stored"] + ["duplicate"] * 4 and d["live_after_guard"] == 1
    assert d["thin_record"]["what_agent_gets"] == "neutral" and d["thin_record"]["precision_shown"] is None


@pytest.mark.s5
@pytest.mark.live
def test_s5_lifecycle(name):
    r = s5_lifecycle.run(name)
    assert not r["hot"]["has_source"] and r["hot"]["reviewed_by_anyone"] is False
    assert r["background"]["chat_calls"] == 0 and r["background"]["decisions"] == ["stored"] and r["background"]["has_source"]
    assert r["life"]["history_rows_for_old_memory"] == [("v1", "ADD", "inactive"), ("v2", "SOFT_DELETE", "inactive")]
    assert r["life"]["replay_matches_what_case_saw"]


@pytest.mark.s6
@pytest.mark.live
def test_s6_multi_agent(name):
    r = s6_multi_agent.run(name)
    owners = {"consolidator": "precedent", "sme_feedback": "sme_correction", "admin": "role_preference", "RAN_A1_intake": "agent_tag"}
    for writer, row in r["write"].items():
        for kind, status in row.items():
            assert status == ("stored" if owners.get(writer) == kind else "rejected"), (writer, kind, status)
    rd = r["read"]
    assert rd["rca_sees_site_precedent"] and rd["rca_sees_global_sme_correction"]
    assert not rd["rca_sees_intakes_private_tag"] and not rd["rca_sees_role_preference"]
    assert rd["intake_sees_its_own_tag"] and rd["intake_sees_global_sme_correction"] and not rd["intake_sees_site_precedent"]
    assert "REJECTED" in r["rules"]["rule1_reply"]
    assert r["rules"]["same_source_confidence"] == "medium" and r["rules"]["different_sources_confidence"] == "high"


@pytest.mark.e2e
@pytest.mark.live
def test_e2e(name):
    r = e2e_case.run(name)
    assert r["seeded"] == ["stored"] and r["proposed"] == ["pending_sme"] and r["approved"] == ["approved"]
    assert any("7 of 9" in t for t in r["run1"]["memory_seen"])      # run 1 saw the old count
    assert any("7 of 10" in t for t in r["run2"]["memory_seen"])     # run 2 saw the new count
    assert not any("7 of 9" in t for t in r["run2"]["memory_seen"])  # and no longer the old one
    for run in ("run1", "run2"):
        assert r[run]["verdict"], f"{run} produced no verdict"
        assert r[run]["verdict"]["category"] in CATEGORIES
    assert r["ledger_after"]["sample_size"] == 87
    with psycopg.connect(config.DATABASE_URL) as conn:               # the demo data must be exactly as before
        assert conn.execute("SELECT count(*) FROM ledger.outcomes").fetchone()[0] == 90
