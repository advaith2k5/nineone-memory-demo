"""Exploration, not a test: what do LangMem and Mem0 do ON THEIR OWN when new information contradicts
an existing memory? Prints before / after so we can describe it truthfully.

Gemini use: about 4-6 chat calls.
Run:  .venv/Scripts/python.exe scripts/probe_library_default.py
"""
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from langmem import create_memory_store_manager  # noqa: E402

from nineone_mem.llm import COUNTER, get_chat_model  # noqa: E402
from nineone_mem.memory.base import Scope  # noqa: E402
from nineone_mem.memory.langmem_backend import LangMemBackend  # noqa: E402
from nineone_mem.memory.mem0_backend import Mem0Backend  # noqa: E402

OLD = "A 2 degree tilt change worked on cell RNA1301000057_1."
NEW_CONVERSATION = [
    {"role": "user", "content": "Update from the latest closed case: the 2 degree tilt change on cell "
                                "RNA1301000057_1 did NOT work. Accessibility fell again within a day."},
]


def show(title, backend, scope):
    print(f"  {title}:")
    for r in backend.list(scope):
        print(f"    - [{r.id[:8]}] {r.content}")
    if not backend.list(scope):
        print("    (nothing)")


def probe_langmem():
    print("\n=== LangMem (create_memory_store_manager, enable_deletes=True) ===")
    b = LangMemBackend()
    scope = Scope("site", tenant=f"probe_{uuid.uuid4().hex[:6]}", site_id="TOK-104", cell_id="RNA1301000057_1")
    b.add(OLD, scope)
    show("before", b, scope)
    manager = create_memory_store_manager(get_chat_model(), namespace=scope.namespace, store=b.store,
                                          enable_inserts=True, enable_deletes=True)
    result = manager.invoke({"messages": NEW_CONVERSATION})
    print("  manager returned:", result)
    show("after", b, scope)
    b.close()


def probe_mem0():
    print("\n=== Mem0 (add with infer=True) ===")
    b = Mem0Backend()
    scope = Scope("site", tenant=f"probe_{uuid.uuid4().hex[:6]}", site_id="TOK-104", cell_id="RNA1301000057_1")
    old = b.add(OLD, scope)
    show("before", b, scope)
    res = b.mem.add(NEW_CONVERSATION, metadata=scope.metadata, **b._entity(scope), infer=True)
    print("  mem0 returned:", [(r.get("event"), r.get("memory")) for r in res.get("results", [])])
    show("after", b, scope)
    print("  history of the old memory:", [(h["event"], h["old_memory"], h["new_memory"]) for h in b.history(old.id)])
    b.close()


if __name__ == "__main__":
    chosen = sys.argv[1:] or ["langmem", "mem0"]       # e.g.  probe_library_default.py langmem
    for fn in (probe_langmem, probe_mem0):
        if fn.__name__.removeprefix("probe_") not in chosen:
            continue
        try:
            fn()
        except Exception as e:     # show the failure honestly instead of hiding it
            print(f"  FAILED: {type(e).__name__}: {str(e)[:400]}")
    print("\n" + COUNTER.summary())
