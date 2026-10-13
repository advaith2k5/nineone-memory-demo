-- Setup for the NineOne memory demo.
-- LangMem's PostgresStore and Mem0 create their OWN tables for vectors later.
-- This file only holds the tables WE own.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS ran;
CREATE SCHEMA IF NOT EXISTS ledger;
CREATE SCHEMA IF NOT EXISTS mock;

-- ---------- mock network data (stands in for PM / FM / CM feeds) ----------
-- Read by the get_case_facts tool. This is "today's numbers", NOT memory.

CREATE TABLE IF NOT EXISTS mock.pm_kpi (
  cell_id      text NOT NULL,
  kpi          text NOT NULL,           -- e.g. 'accessibility'
  window_start timestamptz NOT NULL,
  window_end   timestamptz NOT NULL,
  value        numeric NOT NULL,
  target       numeric NOT NULL
);

CREATE TABLE IF NOT EXISTS mock.fm_alarm (
  cell_id    text NOT NULL,
  alarm_text text NOT NULL,
  severity   text NOT NULL,             -- MINOR | MAJOR | CRITICAL
  raised_at  timestamptz NOT NULL,
  cleared_at timestamptz
);

CREATE TABLE IF NOT EXISTS mock.cm_change (
  cell_id    text NOT NULL,
  parameter  text NOT NULL,             -- e.g. 'electrical_tilt'
  old_value  text,
  new_value  text,
  changed_at timestamptz NOT NULL,
  authorised boolean NOT NULL
);

-- ---------- case record: one investigation (v3 "case record" home) ----------
-- Same shape as the table in "Nineone Memory- RnD.md" (ran.agent_evidence),
-- with the writer column added so we can prove "one writer per row".
CREATE TABLE IF NOT EXISTS ran.agent_evidence (
  id              bigserial PRIMARY KEY,
  pipeline_run_id text NOT NULL,        -- = thread_id
  site_id         text NOT NULL,
  cell_id         text,
  agent           text NOT NULL,        -- e.g. 'RAN_A3_config'
  verdict         text NOT NULL,
  gate            text NOT NULL,        -- passed | blocked | awaiting_human
  confidence      text,
  payload         jsonb NOT NULL,       -- must carry rule_id + sources (citation rule)
  written_by      text NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (pipeline_run_id, agent, site_id, cell_id)
);

-- ---------- outcome ledger (v3 memory #6): ONLY RAN_A9 may write ----------
CREATE TABLE IF NOT EXISTS ledger.outcomes (
  id            bigserial PRIMARY KEY,
  case_id       text NOT NULL,
  site_id       text NOT NULL,
  cell_id       text NOT NULL,
  finding_type  text NOT NULL,          -- e.g. 'unauthorised_change_before_onset'
  cell_class    jsonb NOT NULL,         -- {"site_type":"macro","clutter":"urban","band":"1.7GHz"}
  action_taken  text NOT NULL,          -- e.g. 'revert_tilt_change'
  held          boolean NOT NULL,       -- did the fix hold?
  observed_at   timestamptz NOT NULL,
  written_by    text NOT NULL DEFAULT 'RAN_A9_action_watcher',
  CONSTRAINT only_a9_writes CHECK (written_by = 'RAN_A9_action_watcher')
);

-- ---------- proposed memories waiting for a decision (the NineOne guard's queue) ----------
-- A memory only reaches LangMem / Mem0 after passing the guard. Anything that changes an
-- existing memory waits here for a (simulated) SME. Rejected and quarantined ones are kept too.
CREATE TABLE IF NOT EXISTS ran.memory_candidates (
  id             bigserial PRIMARY KEY,
  backend        text NOT NULL,
  scope          jsonb NOT NULL,
  content        text NOT NULL,
  kind           text NOT NULL,           -- precedent | sme_correction | role_preference
  topic          text,                    -- same topic + different text = a conflict
  writer         text NOT NULL,
  sources        jsonb NOT NULL DEFAULT '[]',
  status         text NOT NULL,           -- pending_sme | approved | rejected | quarantined | stored
  reason         text,
  conflicts_with text,                    -- id of the live memory it would replace
  created_at     timestamptz NOT NULL DEFAULT now(),
  decided_by     text,                    -- a ROLE, never a person (v3 MI-9)
  decided_at     timestamptz
);

-- ---------- our own memory history (LangMem overwrites by key; we keep versions) ----------
-- Soft delete: rows are never removed, only marked inactive (v3 MI-6 replay).
CREATE TABLE IF NOT EXISTS ran.memory_history (
  id           bigserial PRIMARY KEY,
  backend      text NOT NULL,           -- 'langmem' | 'mem0'
  memory_key   text NOT NULL,
  namespace    text NOT NULL,           -- e.g. 'tenantA/site/S1/cell/RNA..._1'
  version      int  NOT NULL,
  content      text NOT NULL,
  event        text NOT NULL,           -- ADD | UPDATE | SOFT_DELETE
  reason       text,
  written_by   text NOT NULL,
  sources      jsonb,                   -- citations
  active       boolean NOT NULL,
  valid_from   timestamptz NOT NULL DEFAULT now(),
  valid_to     timestamptz,
  UNIQUE (backend, memory_key, version)
);
