"""The one memory interface both LangMem and Mem0 must follow.

Every scenario talks to a MemoryBackend, never to a library directly. That is
what lets us run the same scenario on both and compare the results fairly.

Scope answers "whose memory is this?". It follows the HLD: tenant > agent > site/cell > role.
(No per-person level: v3 rule MI-9 says operators are stored as roles only.)
"""
from __future__ import annotations  # needed: the method named `list` below would shadow the built-in in type hints

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .. import config


@dataclass(frozen=True)
class Scope:
    # "site" = memories about ONE CELL (site_id + cell_id). A site-only search with this level is a
    #          prefix search that also returns the site's other cells (the wrong-cell problem, scenario 2).
    # "sitewide" = memories about the site as a whole. It lives in its OWN branch, so it never mixes
    #          with any cell's memories.
    level: str                       # "global" | "agent" | "site" | "sitewide" | "role"
    tenant: str = config.TENANT
    agent_id: str | None = None      # e.g. "RAN_A8_rca"
    site_id: str | None = None       # e.g. "TOK-104"
    cell_id: str | None = None       # e.g. "RNA1301000057_1" (only with site_id)
    role: str | None = None          # e.g. "noc_l2"

    def __post_init__(self):
        if self.level not in ("global", "agent", "site", "sitewide", "role"):
            raise ValueError(f"unknown scope level: {self.level}")
        if self.cell_id and not self.site_id:
            raise ValueError("cell_id needs site_id")
        if self.level == "sitewide" and (self.cell_id or not self.site_id):
            raise ValueError("sitewide needs site_id and no cell_id")

    @property
    def namespace(self) -> tuple[str, ...]:
        """LangMem-style address, e.g. ('tenantA','site','TOK-104','RNA1301000057_1').
        Searching with a SHORTER tuple matches everything below it (prefix search)."""
        parts = [self.tenant, self.level]
        for v in (self.agent_id, self.site_id, self.cell_id, self.role):
            if v:
                parts.append(v)
        return tuple(parts)

    @property
    def metadata(self) -> dict:
        """Mem0-style address: flat key/values stored with each memory and used as filters."""
        out = {"tenant": self.tenant, "scope": self.level}
        for k in ("agent_id", "site_id", "cell_id", "role"):
            if getattr(self, k):
                out[k] = getattr(self, k)
        return out


@dataclass
class MemoryRecord:
    id: str
    content: str
    scope: Scope | None = None
    score: float | None = None       # similarity, higher = closer (None when not from a search)
    metadata: dict = field(default_factory=dict)


class MemoryBackend(ABC):
    name: str = "base"

    @abstractmethod
    def add(self, content: str, scope: Scope, metadata: dict | None = None) -> MemoryRecord:
        """Save one memory exactly as given. NO LLM call (keeps setup free of quota)."""

    @abstractmethod
    def search(self, query: str, scope: Scope, limit: int = 3) -> list[MemoryRecord]:
        """Meaning-based search inside `scope`. A site scope also matches its cells."""

    @abstractmethod
    def list(self, scope: Scope) -> list[MemoryRecord]:
        """Everything stored inside `scope`, no ranking."""

    @abstractmethod
    def update(self, memory_id: str, content: str, scope: Scope) -> MemoryRecord:
        """Replace the text of one memory."""

    @abstractmethod
    def delete(self, memory_id: str, scope: Scope) -> None:
        """HARD delete inside the library. NineOne's guard does soft deletes on top of this."""

    @abstractmethod
    def history(self, memory_id: str) -> list[dict]:
        """What the LIBRARY itself remembers about changes to this memory (may be empty)."""

    @abstractmethod
    def _library_extract(self, messages: list[dict], scope: Scope) -> None:
        """Hand a conversation to the library's OWN LLM-based memory logic and let it decide what to
        add / update / delete. Uses chat calls. Each library does this differently."""

    def extract(self, messages: list[dict], scope: Scope) -> list[dict]:
        """Run the library's own LLM path and report what it did, by comparing before and after.

        Same report for both libraries, so they can be compared:
        [{"event": "ADD"|"UPDATE"|"DELETE", "id": ..., "before": text|None, "after": text|None}]
        """
        before = {r.id: r.content for r in self.list(scope)}
        self._library_extract(messages, scope)
        after = {r.id: r.content for r in self.list(scope)}
        events = []
        for mid, text in after.items():
            if mid not in before:
                events.append({"event": "ADD", "id": mid, "before": None, "after": text})
            elif before[mid] != text:
                events.append({"event": "UPDATE", "id": mid, "before": before[mid], "after": text})
        for mid, text in before.items():
            if mid not in after:
                events.append({"event": "DELETE", "id": mid, "before": text, "after": None})
        return events

    def close(self) -> None:
        """Release connections. Optional."""
