"""Mem0 version of the memory interface.

Mem0 is a complete memory layer: it embeds, stores, searches AND can use an LLM
to decide ADD / UPDATE / DELETE. This backend uses it in the same plain way as
the LangMem one (no LLM) so the two can be compared fairly. The LLM decisions
are used later, in the conflict scenario.

Wiring choices (and why):
- vector store: our Postgres + pgvector, 768 numbers, HNSW index
- embedder: Mem0's "langchain" embedder holding OUR NormalizedEmbeddings
  (Mem0's own Gemini embedder does not normalize vectors)
- LLM: Mem0's native "gemini" provider (its "langchain" adapter breaks on
  Gemini's list-style replies), wrapped so calls respect our rate limit and counter
- history: Mem0 keeps old versions in a small SQLite file, NOT in Postgres
"""
from __future__ import annotations  # a method here is named `list`

from .. import config  # must come BEFORE `import mem0`: it switches Mem0 telemetry off

from mem0 import Memory  # noqa: E402
from ..llm import NormalizedEmbeddings, wait_for_chat_slot
from .base import MemoryBackend, MemoryRecord, Scope

HISTORY_DB = str(config.ROOT / "mem0_history.db")


class Mem0Backend(MemoryBackend):
    name = "mem0"

    def __init__(self) -> None:
        self.mem = Memory.from_config({
            "vector_store": {
                "provider": "pgvector",
                "config": {
                    "connection_string": config.DATABASE_URL,
                    "collection_name": "mem0_nineone",
                    "embedding_model_dims": config.EMBED_DIMS,
                    "hnsw": True,
                },
            },
            "llm": {
                "provider": "gemini",
                "config": {"model": config.MEMORY_MODEL, "api_key": config.GOOGLE_API_KEY, "temperature": 0},
            },
            "embedder": {"provider": "langchain", "config": {"model": NormalizedEmbeddings()}},
            "history_db_path": HISTORY_DB,
        })
        self._wrap_llm_with_rate_limit()

    def _wrap_llm_with_rate_limit(self) -> None:
        original = self.mem.llm.generate_response

        def throttled(*args, **kwargs):
            wait_for_chat_slot()
            return original(*args, **kwargs)

        self.mem.llm.generate_response = throttled

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _meta(scope: Scope) -> dict:
        # "agent_id" is RESERVED by Mem0 (its entity id). Our scope also has an agent_id, and using the
        # same key made the two overwrite each other: an agent could not find its own memories
        # (found by scenario 6). So our value is stored under a different name.
        return {("owner_agent" if k == "agent_id" else k): v for k, v in scope.metadata.items()}

    @staticmethod
    def _filters(scope: Scope) -> dict:
        # Mem0 has no nested namespaces. We store the scope as flat metadata and
        # filter on it. Leaving cell_id out of the filter = "whole site", like a prefix.
        # Mem0 also REFUSES any search without an entity id, so that goes in the filter too.
        return {**Mem0Backend._entity(scope), **Mem0Backend._meta(scope)}

    @staticmethod
    def _entity(scope: Scope) -> dict:
        # Mem0 wants at least one entity id on every add. We use the tenant + level as a
        # plain label. It is NOT a person (v3 rule MI-9: no individual operators in memory).
        return {"agent_id": "/".join(scope.namespace[:2])}

    def _to_record(self, item: dict, scope: Scope | None) -> MemoryRecord:
        meta = dict(item.get("metadata") or {})
        return MemoryRecord(
            id=item["id"],
            content=item["memory"],
            scope=scope,
            score=item.get("score"),
            metadata=meta,
        )

    # -- interface ---------------------------------------------------------
    def add(self, content: str, scope: Scope, metadata: dict | None = None) -> MemoryRecord:
        # infer=False = store the text exactly as given, no LLM call.
        res = self.mem.add(content, metadata={**self._meta(scope), **(metadata or {})}, infer=False, **self._entity(scope))
        first = res["results"][0]
        return MemoryRecord(id=first["id"], content=content, scope=scope, metadata=metadata or {})

    def search(self, query: str, scope: Scope, limit: int = 3) -> list[MemoryRecord]:
        res = self.mem.search(query, top_k=limit, filters=self._filters(scope))
        return [self._to_record(r, scope) for r in res["results"]]

    def list(self, scope: Scope) -> list[MemoryRecord]:
        res = self.mem.get_all(filters=self._filters(scope), top_k=1000)
        return [self._to_record(r, scope) for r in res["results"]]

    def update(self, memory_id: str, content: str, scope: Scope) -> MemoryRecord:
        self.mem.update(memory_id, text=content)
        return MemoryRecord(id=memory_id, content=content, scope=scope)

    def delete(self, memory_id: str, scope: Scope) -> None:
        self.mem.delete(memory_id)

    def history(self, memory_id: str) -> list[dict]:
        return self.mem.history(memory_id)   # Mem0 DOES keep old versions (in SQLite)

    def _library_extract(self, messages: list[dict], scope: Scope) -> None:
        # Mem0's own path: infer=True makes its LLM pull out facts and decide what to store.
        # Observed (Mem0 2.2.1 + gemini-3.1-flash-lite): a contradicting fact was ADDED next to the
        # old one; the old memory stayed live.
        self.mem.add(messages, metadata=self._meta(scope), infer=True, **self._entity(scope))
