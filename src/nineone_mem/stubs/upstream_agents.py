"""The five agents that run BEFORE RCA (E2E steps 1-5), as rule-only stubs. No AI, no memory writes.

  RAN_A1  Intake       picks the worst cell
  RAN_A2  Fault (FM)   reads alarms
  RAN_A3  Config (CM)  reads parameter changes
  RAN_A5  Coverage     has no data feed in this demo (a known gap)
  (Performance)        reads the KPI. Its real RAN_A number is TBD, so it is named by role.

Each one writes ONE finding about the cell. RCA reads those findings and decides.
"""
from __future__ import annotations

import psycopg

from .. import config
from .common import window_start, write_finding

MAJOR = ("MAJOR", "CRITICAL")


def _q(sql: str, *args):
    with psycopg.connect(config.DATABASE_URL) as conn:
        return conn.execute(sql, args).fetchall()


def run_intake(run_id: str, site_id: str, cell_id: str) -> None:
    # ORDER BY makes "the first row" always the same one: the KPI furthest below its target.
    rows = _q("SELECT kpi, value, target FROM mock.pm_kpi WHERE cell_id=%s AND value < target"
              " ORDER BY (target - value) DESC, kpi", cell_id)
    if rows:
        kpi, value, target = rows[0]
        write_finding("RAN_A1_intake", run_id, site_id, cell_id, "worst_cell_selected", None, ["pm_counters"],
                      f"{kpi} {float(value)} is below its target {float(target)}.")
    else:
        write_finding("RAN_A1_intake", run_id, site_id, cell_id, "not_a_worst_cell", None, ["pm_counters"],
                      "No KPI is below target for this cell.")


def run_fault(run_id: str, site_id: str, cell_id: str) -> None:
    # Most severe alarm first, then the most recent, so the finding does not depend on row order.
    alarms = _q("SELECT alarm_text, severity FROM mock.fm_alarm WHERE cell_id=%s"
                " ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'MAJOR' THEN 1 ELSE 2 END, raised_at DESC",
                cell_id)
    if not alarms:
        write_finding("RAN_A2_fault", run_id, site_id, cell_id, "no_alarm", None, ["fm_alarm"], "No alarms on this cell.")
        return
    text, severity = alarms[0]
    if severity in MAJOR:
        write_finding("RAN_A2_fault", run_id, site_id, cell_id, "service_affecting_alarm", "fault", ["fm_alarm"],
                      f"{severity} alarm: {text}.", weight="high")
    else:
        # v3 memory #5: a minor alarm cannot affect accessibility, so it is weighted down.
        write_finding("RAN_A2_fault", run_id, site_id, cell_id, "minor_alarm_not_service_affecting", "fault",
                      ["fm_alarm"], f"{severity} alarm: {text}. Not service-affecting.", weight="low")


def run_config(run_id: str, site_id: str, cell_id: str) -> None:
    start = window_start(cell_id)
    if start is None:
        write_finding("RAN_A3_config", run_id, site_id, cell_id, "no_kpi_window", None, ["cm_change"],
                      "No KPI window, so changes cannot be compared with the onset.")
        return
    changes = _q("SELECT parameter, old_value, new_value, changed_at, authorised FROM mock.cm_change"
                 " WHERE cell_id=%s AND changed_at < %s ORDER BY changed_at DESC", cell_id, start)
    unauthorised = [c for c in changes if not c[4]]
    if unauthorised:
        p, old, new, at, _ = unauthorised[0]
        write_finding("RAN_A3_config", run_id, site_id, cell_id, "unauthorised_change_before_onset", "config_change",
                      ["cm_change"], f"{p} changed {old} -> {new} at {at:%H:%M} UTC without authorisation, before the drop.")
    else:
        write_finding("RAN_A3_config", run_id, site_id, cell_id, "no_unauthorised_change", None, ["cm_change"],
                      "No unauthorised change before the drop.")


def run_coverage(run_id: str, site_id: str, cell_id: str) -> None:
    # Known gap (AGENTS.md): no measurement-report feed in this demo, so this agent cannot say anything.
    write_finding("RAN_A5_coverage", run_id, site_id, cell_id, "no_coverage_feed", None, [],
                  "No measurement-report feed is connected.")


def run_performance(run_id: str, site_id: str, cell_id: str) -> None:
    rows = _q("SELECT kpi, value, target FROM mock.pm_kpi WHERE cell_id=%s ORDER BY (target - value) DESC, kpi", cell_id)
    if not rows:
        write_finding("RAN_PERF_performance", run_id, site_id, cell_id, "no_kpi_data", None, ["pm_counters"],
                      "No KPI rows for this window.")
        return
    kpi, value, target = rows[0]
    gap = round(float(target) - float(value), 1)    # arithmetic done HERE, in code, never by the model
    write_finding("RAN_PERF_performance", run_id, site_id, cell_id, "kpi_below_target" if gap > 0 else "kpi_ok", None,
                  ["pm_counters"], f"{kpi} is {float(value)} against a target of {float(target)} (gap {gap}).")


def run_upstream_agents(run_id: str, site_id: str, cell_id: str) -> None:
    """E2E steps 1-5 in order."""
    for step in (run_intake, run_performance, run_config, run_fault, run_coverage):
        step(run_id, site_id, cell_id)
