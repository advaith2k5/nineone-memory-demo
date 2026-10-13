"""The NineOne guard. It sits ON TOP of LangMem / Mem0.

Neither library enforces NineOne's rules, so nothing reaches them except through here.
Every check below comes from a rule in Saurabh's v3 doc or the harness template.

    candidate memory --> [owner?] [right home?] [person data?] [injection?] [cites real sources?]
                         [duplicate?] [conflicts with a live memory?] --> stored / waits for SME / refused

Honest limits: the person-data and injection checks are simple pattern lists. They catch the
obvious cases, not every clever one. The second layer is the wrapper around memory text and the
"memory is data, never instructions" ban in soul.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import psycopg
from psycopg.types.json import Jsonb

from .. import config
from .base import MemoryBackend, MemoryRecord, Scope

# v3 section 1: one writer per kind of memory.
OWNER = {"precedent": "consolidator", "sme_correction": "sme_feedback", "role_preference": "admin",
         "agent_tag": "RAN_A1_intake"}      # v3: the repeat-offender tag lives in the Intake agent's own kit
# v3 section 1: memory lives where the thing it describes lives.
HOME = {"precedent": {"site", "sitewide"}, "sme_correction": {"global", "sitewide", "site"},
        "role_preference": {"role"}, "agent_tag": {"agent"}}
APPROVER_ROLES = {"sme"}            # a role, never a person (v3 MI-9)
# Memories that come from a person's decision, not from a closed case, cite a record of that decision.
# The guard checks the SHAPE of this id. It cannot check that a real review exists (known limit).
DECISION_SOURCE = {"sme_correction": "sme_review:", "role_preference": "admin_request:"}

PERSON_PATTERNS = [
    r"[\w.+-]+@[\w-]+\.[\w.]+",                      # email
    r"\+\d[\d\s-]{8,}\d",                            # phone with country code
    r"\b\d{3}[-\s]\d{3}[-\s]\d{4}\b",                # phone 3-3-4
    r"\b(?:Mr|Mrs|Ms|Dr)\.?\s+[A-Z][a-z]+",          # titled name
]
INJECTION_PATTERNS = [
    r"ignore (all|any|the|previous|prior|above)[^.]{0,40}(rules|instructions|prompt)",
    r"disregard (all|any|the|previous|prior)",
    r"system prompt",
    r"you (must|should|will) now",
    r"mark (this|the|it)( case)?( as)? (resolved|closed|passed)",
    r"</?\s*memory",
    r"act as ",
]


@dataclass
class Candidate:
    content: str
    scope: Scope
    kind: str                         # precedent | sme_correction | role_preference
    writer: str                       # who is proposing it
    sources: list[str] = field(default_factory=list)   # case ids / evidence run ids / sme_review:<id>
    topic: str | None = None          # same topic + different text = a conflict


@dataclass
class Decision:
    status: str                       # stored | pending_sme | rejected | quarantined | duplicate | approved
    reason: str = ""
    memory_id: str | None = None
    candidate_id: int | None = None
    conflicts_with: str | None = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())




class MemoryGuard:
    def __init__(self, backend: MemoryBackend) -> None:
        self.backend = backend

    # ------------------------------------------------------------------ propose
    def propose(self, c: Candidate) -> Decision:
        for check, status in ((self._check_owner, "rejected"), (self._check_home, "rejected"),
                              (self._check_person, "rejected"), (self._check_injection, "quarantined"),
                              (self._check_citation, "rejected")):
            why = check(c)
            if why:
                return self._record(c, status, why)

        dup = self._find_duplicate(c)
        if dup:
            return self._record(c, "duplicate", f"same as live memory {dup.id}", conflicts_with=dup.id)

        clash = self._find_conflict(c)
        if clash:
            return self._record(c, "pending_sme", f"disagrees with live memory {clash.id}; needs SME approval",
                                conflicts_with=clash.id)
        return self._store(c, status="stored")

    # ------------------------------------------------------------ SME decisions
    def approve(self, candidate_id: int, approver_role: str = "sme") -> Decision:
        row = self._load(candidate_id)
        refusal = self._check_decider(row, candidate_id, approver_role)
        if refusal:
            return refusal
        c = self._to_candidate(row)
        if row["conflicts_with"]:
            self.soft_delete(row["conflicts_with"], c.scope, f"superseded by candidate {candidate_id}", approver_role)
        d = self._store(c, status="approved", candidate_id=candidate_id, decided_by=approver_role,
                        extra={"supersedes": row["conflicts_with"]})
        return d

    def reject(self, candidate_id: int, approver_role: str, reason: str) -> Decision:
        # Same two checks as approve(): only an approver ROLE may decide, and only a PENDING candidate.
        # (Before, reject() skipped both, so anyone could overwrite the status of any candidate.)
        refusal = self._check_decider(self._load(candidate_id), candidate_id, approver_role)
        if refusal:
            return refusal
        self._set_status(candidate_id, "rejected", reason, approver_role)
        return Decision("rejected", reason, candidate_id=candidate_id)

    def _check_decider(self, row: dict, candidate_id: int, approver_role: str) -> Decision | None:
        if row["status"] != "pending_sme":
            return Decision("rejected", f"candidate {candidate_id} is {row['status']}, not pending", candidate_id=candidate_id)
        if approver_role not in APPROVER_ROLES or self._check_person(Candidate(approver_role, Scope("global"), "", "")):
            return Decision("rejected", f"'{approver_role}' is not an approver role", candidate_id=candidate_id)
        return None

    # -------------------------------------------------------------- soft delete
    def soft_delete(self, memory_id: str, scope: Scope, reason: str, by: str) -> None:
        """Remove from search, but keep the full text and who/when/why in ran.memory_history."""
        live = next((r for r in self.backend.list(scope) if r.id == memory_id), None)
        if live is None:
            raise KeyError(f"memory {memory_id} not found in {scope.namespace}")
        # Order matters. The history rows are written inside a transaction that is only committed AFTER
        # the library delete succeeds. If the delete fails, the transaction rolls back, so history never
        # says "deleted" about a memory that is still live. If the history write fails first, nothing is
        # deleted at all. (Before, the delete ran first: a failed history write left a deleted memory
        # with no record.)
        with psycopg.connect(config.DATABASE_URL) as conn:
            conn.execute("UPDATE ran.memory_history SET active=false, valid_to=now()"
                         " WHERE backend=%s AND memory_key=%s AND active", (self.backend.name, memory_id))
            conn.execute(
                "INSERT INTO ran.memory_history (backend, memory_key, namespace, version, content, event, reason,"
                " written_by, sources, active, valid_from, valid_to) SELECT %s,%s,%s,"
                " coalesce(max(version),0)+1,%s,'SOFT_DELETE',%s,%s,%s,false,now(),now()"
                " FROM ran.memory_history WHERE backend=%s AND memory_key=%s",
                (self.backend.name, memory_id, "/".join(scope.namespace), live.content, reason, by,
                 Jsonb(live.metadata.get("sources", [])), self.backend.name, memory_id))
            self.backend.delete(memory_id, scope)    # raises -> the `with` block rolls the history back

    # ----------------------------------------------------------------- queries
    def as_of(self, scope: Scope, when) -> list[dict]:
        """What this scope remembered at a past moment (v3 MI-7), read from our own history."""
        with psycopg.connect(config.DATABASE_URL) as conn:
            rows = conn.execute(
                "SELECT memory_key, content, valid_from FROM ran.memory_history WHERE backend=%s AND namespace=%s"
                " AND event IN ('ADD','UPDATE') AND valid_from <= %s AND (valid_to IS NULL OR valid_to > %s)"
                " ORDER BY valid_from", (self.backend.name, "/".join(scope.namespace), when, when)).fetchall()
        return [{"memory_key": k, "content": c, "valid_from": v} for k, c, v in rows]

    def pending(self, tenant: str | None = None) -> list[dict]:
        """Candidates waiting for an SME. Pass `tenant` to see only one tenant's queue. (Without it you get
        every tenant's, which is what a global review screen would want but a test never does.)"""
        sql = "SELECT * FROM ran.memory_candidates WHERE backend=%s AND status='pending_sme'"
        args: list = [self.backend.name]
        if tenant is not None:
            sql += " AND scope->>'tenant' = %s"
            args.append(tenant)
        with psycopg.connect(config.DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
            return conn.execute(sql + " ORDER BY id", args).fetchall()

    # ------------------------------------------------------------------ checks
    def _check_owner(self, c: Candidate) -> str | None:
        owner = OWNER.get(c.kind)
        if owner is None:
            return f"unknown memory kind '{c.kind}'"
        if c.writer != owner:
            return f"'{c.writer}' may not write '{c.kind}' memories; the one owner is '{owner}'"
        return None

    def _check_home(self, c: Candidate) -> str | None:
        if c.scope.level not in HOME.get(c.kind, set()):
            return f"'{c.kind}' memories do not live at scope '{c.scope.level}'; allowed: {sorted(HOME[c.kind])}"
        return None

    @staticmethod
    def _check_person(c: Candidate) -> str | None:
        for p in PERSON_PATTERNS:
            if re.search(p, c.content):
                return "contains personal data (email, phone or a named person); roles only (v3 MI-9)"
        return None

    @staticmethod
    def _check_injection(c: Candidate) -> str | None:
        for p in INJECTION_PATTERNS:
            if re.search(p, c.content, flags=re.I):
                return "looks like an instruction to the agent, not a note; quarantined for a person to look at"
        return None

    def _check_citation(self, c: Candidate) -> str | None:
        if not c.sources:
            return "no sources: every memory must cite where it came from"
        unknown = []
        with psycopg.connect(config.DATABASE_URL) as conn:
            for s in set(c.sources):
                if s.startswith(DECISION_SOURCE.get(c.kind, "\0")):
                    continue
                hit = conn.execute("SELECT 1 FROM ledger.outcomes WHERE case_id=%s UNION ALL"
                                   " SELECT 1 FROM ran.agent_evidence WHERE pipeline_run_id=%s LIMIT 1", (s, s)).fetchone()
                if not hit:
                    unknown.append(s)
        return f"cited sources do not exist: {unknown}" if unknown else None

    def _find_duplicate(self, c: Candidate) -> MemoryRecord | None:
        """A duplicate is the SAME TEXT (ignoring case and spacing). Nothing fuzzier.

        We first tried "similar enough by embedding" and it silently dropped real changes:
        "held in 7 of 9" vs "7 of 10" scored 0.97+, and "served by vCU-A" vs "vCU-B" too. An embedding
        cannot tell a paraphrase from a changed fact, at any threshold. So changes are caught by the
        TOPIC key instead (see _find_conflict) and go to an SME. Free text with no topic is kept as
        written, so a reworded repeat of a fact can still pile up. That is a known limit.
        """
        return next((r for r in self.backend.list(c.scope) if _norm(r.content) == _norm(c.content)), None)

    def _find_conflict(self, c: Candidate) -> MemoryRecord | None:
        if not c.topic:
            return None
        return next((r for r in self.backend.list(c.scope) if r.metadata.get("topic") == c.topic), None)

    # ----------------------------------------------------------------- storage
    def _store(self, c: Candidate, status: str, candidate_id: int | None = None, decided_by: str | None = None,
               extra: dict | None = None) -> Decision:
        meta = {"topic": c.topic, "kind": c.kind, "writer": c.writer, "sources": c.sources, **(extra or {})}
        rec = self.backend.add(c.content, c.scope, metadata={k: v for k, v in meta.items() if v is not None})
        try:
            with psycopg.connect(config.DATABASE_URL) as conn:
                conn.execute(
                    "INSERT INTO ran.memory_history (backend, memory_key, namespace, version, content, event, reason,"
                    " written_by, sources, active) VALUES (%s,%s,%s,1,%s,'ADD',%s,%s,%s,true)",
                    (self.backend.name, rec.id, "/".join(c.scope.namespace), c.content, c.kind, c.writer, Jsonb(c.sources)))
        except Exception:
            # No history row means replay would not know this memory existed. Take it back out rather than
            # leave a live memory with no record.
            self.backend.delete(rec.id, c.scope)
            raise
        if candidate_id is None:
            d = self._record(c, status, "passed every check", memory_id=rec.id)
            return d
        self._set_status(candidate_id, "approved", "approved", decided_by)
        return Decision("approved", "approved by SME", memory_id=rec.id, candidate_id=candidate_id)

    def _record(self, c: Candidate, status: str, reason: str, conflicts_with: str | None = None,
                memory_id: str | None = None) -> Decision:
        with psycopg.connect(config.DATABASE_URL) as conn:
            cid = conn.execute(
                "INSERT INTO ran.memory_candidates (backend, scope, content, kind, topic, writer, sources, status,"
                " reason, conflicts_with) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (self.backend.name, Jsonb(c.scope.__dict__), c.content, c.kind, c.topic, c.writer, Jsonb(c.sources),
                 status, reason, conflicts_with)).fetchone()[0]
        return Decision(status, reason, memory_id=memory_id, candidate_id=cid, conflicts_with=conflicts_with)

    def _set_status(self, cid: int, status: str, reason: str, by: str | None) -> None:
        with psycopg.connect(config.DATABASE_URL) as conn:
            conn.execute("UPDATE ran.memory_candidates SET status=%s, reason=%s, decided_by=%s, decided_at=now()"
                         " WHERE id=%s", (status, reason, by, cid))

    def _load(self, cid: int) -> dict:
        with psycopg.connect(config.DATABASE_URL, row_factory=psycopg.rows.dict_row) as conn:
            row = conn.execute("SELECT * FROM ran.memory_candidates WHERE id=%s", (cid,)).fetchone()
        if row is None:
            raise KeyError(f"no candidate {cid}")
        return row

    @staticmethod
    def _to_candidate(row: dict) -> Candidate:
        return Candidate(content=row["content"], scope=Scope(**row["scope"]), kind=row["kind"], writer=row["writer"],
                         sources=row["sources"], topic=row["topic"])
