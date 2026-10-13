"""LangMem version of the memory interface.

LangMem itself is a set of helpers (a memory manager, search/save tools). The
actual storage is LangGraph's PostgresStore, so this backend is mostly
PostgresStore with an embedding index. LangMem's LLM-based manager is used
later, in the conflict scenario.

How a memory is stored: namespace tuple + key + a JSON value in LANGMEM'S OWN LAYOUT:

    {"kind": "Memory", "content": {"content": "<the text>"}, "nineone": {<our metadata>}}

LangMem's memory manager reads exactly this shape ("kind" + "content"). A flat {"content": text}
makes it crash with KeyError: 'kind' (found by a probe). Our own metadata lives under the separate
"nineone" key so it can never clash with LangMem's "kind". Only "content.content" is embedded.
"""
from __future__ import annotations  # same reason as base.py: a method here is named `list`

import uuid

from langgraph.store.postgres import PostgresStore
from langmem import create_memory_store_manager

from .. import config
from ..llm import NormalizedEmbeddings, get_chat_model
from .base import MemoryBackend, MemoryRecord, Scope


class LangMemBackend(MemoryBackend):
    name = "langmem"

    def __init__(self) -> None:
        # from_conn_string is a context manager (it owns the DB connection).
        # We enter it by hand and keep it open until close().
        self._ctx = PostgresStore.from_conn_string(
            config.DATABASE_URL,
            index={
                "dims": config.EMBED_DIMS,          # must equal the vector column size
                "embed": NormalizedEmbeddings(),    # 768 numbers, length 1.0
                "fields": ["content.content"],      # only the memory text is embedded
                "distance_type": "cosine",
            },
        )
        self.store = self._ctx.__enter__()
        self.store.setup()   # creates the store + vector tables if missing (safe to repeat)

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _value(content: str, metadata: dict | None) -> dict:
        return {"kind": "Memory", "content": {"content": content}, "nineone": metadata or {}}

    @staticmethod
    def _text(value: dict) -> str:
        c = value["content"]
        # Memories written by LangMem's own manager use the same layout; a bare string is tolerated too.
        return c["content"] if isinstance(c, dict) else str(c)

    @staticmethod
    def _to_record(item, scope: Scope | None = None) -> MemoryRecord:
        return MemoryRecord(
            id=item.key,
            content=LangMemBackend._text(item.value),
            scope=scope,
            score=getattr(item, "score", None),
            metadata={"namespace": "/".join(item.namespace), **item.value.get("nineone", {})},
        )

    # -- interface ---------------------------------------------------------
    def add(self, content: str, scope: Scope, metadata: dict | None = None) -> MemoryRecord:
        key = str(uuid.uuid4())
        self.store.put(scope.namespace, key, self._value(content, metadata))
        return MemoryRecord(id=key, content=content, scope=scope, metadata=metadata or {})

    def search(self, query: str, scope: Scope, limit: int = 3) -> list[MemoryRecord]:
        # namespace_prefix does the scoping: a shorter tuple matches everything below it.
        hits = self.store.search(scope.namespace, query=query, limit=limit)
        return [self._to_record(h, scope) for h in hits]

    def list(self, scope: Scope) -> list[MemoryRecord]:
        return [self._to_record(h, scope) for h in self.store.search(scope.namespace, limit=1000)]

    def update(self, memory_id: str, content: str, scope: Scope) -> MemoryRecord:
        old = self.store.get(scope.namespace, memory_id)
        if old is None:
            raise KeyError(f"no memory {memory_id} in {scope.namespace}")
        # put() with the same key OVERWRITES. LangMem keeps no history of the old text.
        self.store.put(scope.namespace, memory_id, self._value(content, old.value.get("nineone")))
        return MemoryRecord(id=memory_id, content=content, scope=scope)

    def delete(self, memory_id: str, scope: Scope) -> None:
        self.store.delete(scope.namespace, memory_id)

    def history(self, memory_id: str) -> list[dict]:
        return []   # PostgresStore keeps no version history. NineOne adds it (ran.memory_history).

    def _library_extract(self, messages: list[dict], scope: Scope) -> None:
        # LangMem's own memory manager: it searches this namespace, asks the LLM what to add / update /
        # delete, and writes straight into the store. Observed: it rewrites a contradicted memory in
        # place (old text gone) and drops our "nineone" metadata.
        manager = create_memory_store_manager(
            get_chat_model(config.MEMORY_MODEL), namespace=scope.namespace, store=self.store,
            enable_inserts=True, enable_deletes=True)
        manager.invoke({"messages": messages})

    def close(self) -> None:
        self._ctx.__exit__(None, None, None)
