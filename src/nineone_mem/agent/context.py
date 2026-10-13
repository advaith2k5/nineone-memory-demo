"""Everything that is fixed for ONE run: which cell, which window, which memory backend.

The tools read the cell from here. The model is never asked to type a cell id,
so it cannot ask for the wrong cell's data or history.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import config
from ..memory.base import MemoryBackend, Scope


@dataclass
class RunContext:
    backend: MemoryBackend
    run_id: str                  # = pipeline_run_id = thread_id
    site_id: str
    cell_id: str
    window: str                  # e.g. "2026-10-12 08:00-11:00 UTC"
    cell_class: dict = field(default_factory=lambda: {"site_type": "macro", "clutter": "urban", "band": "1.7GHz"})
    tenant: str = config.TENANT

    # Filled in while the agent runs. Used to check the final answer and to log
    # which memory versions the case ran under (v3 invariant MI-6).
    seen_finding_ids: set = field(default_factory=set)
    finding_info: dict = field(default_factory=dict)         # id -> {"supports": category, "sources": [...]}
    retrieved_memory_ids: set = field(default_factory=set)
    retrieved_memories: list = field(default_factory=list)   # [{id, content, scope, score}]
    track_records_used: list = field(default_factory=list)
    verdict: dict | None = None
    rejections: list = field(default_factory=list)           # emit_verdict errors, for the tests

    def memory_scopes(self) -> list[Scope]:
        """Where this agent is allowed to READ from: this exact cell, this site as a whole, and tenant-wide."""
        return [
            Scope("site", tenant=self.tenant, site_id=self.site_id, cell_id=self.cell_id),
            Scope("sitewide", tenant=self.tenant, site_id=self.site_id),
            Scope("global", tenant=self.tenant),
        ]
