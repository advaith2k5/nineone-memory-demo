"""Offline checks (no Gemini calls) that the harness files keep their content in the right file.

Rules come from "Nineone Memory- RnD.md" section 6 (lint_harness.py). The last check is ours:
the first two files are cached between runs, so they must not hold anything about one cell.
"""
import re
from pathlib import Path

HARNESS = Path(__file__).resolve().parents[1] / "harness" / "rca"
SOUL = (HARNESS / "soul.md").read_text(encoding="utf-8")
AGENTS = (HARNESS / "AGENTS.md").read_text(encoding="utf-8")
SKILL = (HARNESS / "skills" / "rca-categorise" / "SKILL.md").read_text(encoding="utf-8")


def test_no_dynamic_tokens_in_soul_or_agents():
    # {site_id}, {cell_id}, {run_id} placeholders would break the prompt cache.
    for name, text in (("soul.md", SOUL), ("AGENTS.md", AGENTS)):
        assert not re.search(r"\{(site_id|cell_id|run_id)\}", text), name


def test_no_thresholds_in_soul():
    # Things like "> 2%" or "below 99" belong in AGENTS.md or the skill, not the job brief.
    assert not re.search(r"[<>]=?\s*\d", SOUL)
    assert not re.search(r"\d\s*%", SOUL)


def test_no_step_by_step_procedure_in_agents():
    # AGENTS.md is "what is true". How to do a task belongs in SKILL.md.
    assert not re.search(r"^\s*(\d+[.)]|step\s*\d)", AGENTS, flags=re.I | re.M)


def test_no_knowledge_graph_dump_in_agents():
    # No big alarm-to-KPI tables. A real KG is read through a tool.
    table_rows = [l for l in AGENTS.splitlines() if l.strip().startswith("|")]
    assert len(table_rows) < 8


def test_no_real_cell_or_site_ids_in_the_cached_files():
    # Our own rule: cached files must hold nothing about one cell or one site.
    for name, text in (("soul.md", SOUL), ("AGENTS.md", AGENTS)):
        assert not re.search(r"RNA\d{6,}_\d", text), f"{name} contains a real cell id"
        assert not re.search(r"TOK-\d{2,}", text), f"{name} contains a real site id"


def test_skill_has_the_required_template_rows():
    for row in ("## Goal", "## Inputs", "## Steps", "## Must NOT", "## When to stop and ask",
                "## Word limit", "## Worked examples", "## Done when", "## Failure / fallback"):
        assert row in SKILL, row
    assert "abstain" in SKILL.lower() and "missing data" in SKILL.lower()   # one stop-and-ask example


def test_every_field_the_harness_tells_the_agent_to_fill_exists_in_the_answer_schema():
    # The harness once said `abstained=true` and named boxes `chosen` / `abstain_reason`. Neither is a
    # field the model can fill. Check each field named in the "answer fields" lines against RcaDecision.
    from nineone_mem.agent.schema import RcaDecision
    fields = set(RcaDecision.model_fields)
    named = set()
    for text in (SOUL, SKILL):
        for line in text.splitlines():
            if "→" in line or "emit_verdict" in line.lower() or "tied_with" in line or "`missing`" in line:
                named |= set(re.findall(r"`([a-z_]+)(?:=|`)", line))
    allowed_non_fields = {"get_case_facts", "search_memory", "get_track_record", "emit_verdict", "rca", "pm_kpi",
                          "supporting_finding", "config_change", "fault", "coverage", "capacity", "interference",
                          "neighbour_impact", "external_event", "abstain", "name", "description", "tools"}
    unknown = {n for n in named if n not in fields and n not in allowed_non_fields}
    assert not unknown, f"harness names fields the model cannot fill: {sorted(unknown)}"


def test_the_sample_floor_in_agents_md_matches_the_code():
    from nineone_mem import config
    assert f"Below {config.SAMPLE_FLOOR} cases" in AGENTS, "AGENTS.md says a different floor than config.SAMPLE_FLOOR"
