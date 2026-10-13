"""The same checks for every memory backend (LangMem now, Mem0 added after it).

Calls Gemini ONLY for embeddings (cheap). No chat calls.
Run:  .venv/Scripts/python.exe -m pytest tests/test_backends.py -v -s
"""
import uuid

import pytest

from nineone_mem.memory.base import Scope
from nineone_mem.memory.langmem_backend import LangMemBackend
from nineone_mem.memory.mem0_backend import Mem0Backend

BACKENDS = {"langmem": LangMemBackend, "mem0": Mem0Backend}


@pytest.fixture(params=list(BACKENDS))
def backend(request):
    b = BACKENDS[request.param]()
    yield b
    b.close()


@pytest.fixture
def tenant():
    # Fresh tenant per test = fresh, isolated memory. Nothing to clean up between tests.
    return f"t_{uuid.uuid4().hex[:8]}"


def cell(tenant, site="TOK-104", cell_id="RNA1301000057_1"):
    return Scope("site", tenant=tenant, site_id=site, cell_id=cell_id)


@pytest.mark.live
def test_add_then_search_finds_the_right_memory(backend, tenant):
    s = cell(tenant)
    backend.add("Reverting the 2 degree tilt change held for 7 of 9 similar cases on this site.", s)
    backend.add("Fan speed low alarms on this cell were cleared by a filter clean in March.", s)
    hits = backend.search("did the tilt revert work before?", s, limit=2)
    assert len(hits) == 2
    assert "tilt" in hits[0].content          # the relevant one ranks first
    assert hits[0].score is not None


@pytest.mark.live
def test_scope_isolation_between_sites(backend, tenant):
    backend.add("Tilt revert held here.", cell(tenant, "TOK-104", "RNA1301000057_1"))
    other = cell(tenant, "TOK-105", "RNA1301000060_1")
    assert backend.search("tilt revert", other) == []     # another site must see nothing


@pytest.mark.live
def test_site_search_also_returns_neighbour_cells_but_cell_search_does_not(backend, tenant):
    # This is the root of the wrong-cell problem (scenario 2): two cells on one site.
    a = cell(tenant, "TOK-104", "RNA1301000057_1")
    b = cell(tenant, "TOK-104", "RNA1301000058_1")
    backend.add("Cell 57 accessibility drop was caused by an unauthorised tilt change.", a)
    backend.add("Cell 58 accessibility drop was caused by a baseband board fault.", b)

    site_wide = backend.search("accessibility drop cause", Scope("site", tenant=tenant, site_id="TOK-104"), limit=5)
    assert len(site_wide) == 2                              # both cells come back

    exact = backend.search("accessibility drop cause", a, limit=5)
    assert len(exact) == 1 and "tilt" in exact[0].content   # only this cell's memory


@pytest.mark.live
def test_update_overwrites_and_delete_removes(backend, tenant):
    s = cell(tenant)
    rec = backend.add("2 degree tilt worked.", s)
    backend.update(rec.id, "2 degree tilt did NOT work.", s)
    assert [r.content for r in backend.list(s)] == ["2 degree tilt did NOT work."]
    backend.delete(rec.id, s)
    assert backend.list(s) == []


@pytest.mark.live
def test_an_agent_can_find_its_own_agent_level_memory_and_others_cannot(backend, tenant):
    # Regression: on Mem0, our "agent_id" clashed with Mem0's reserved entity field, so an agent
    # could not find its own memories.
    mine = Scope("agent", tenant=tenant, agent_id="RAN_A1_intake")
    theirs = Scope("agent", tenant=tenant, agent_id="RAN_A3_config")
    backend.add("Cell RNA1301000057_1 was tagged repeat offender.", mine)
    assert len(backend.search("repeat offender", mine)) == 1
    assert backend.search("repeat offender", theirs) == []


@pytest.mark.live
def test_empty_scope_search_returns_empty_list_not_error(backend, tenant):
    # Edge case: the agent must be able to hear "no precedent" instead of crashing.
    assert backend.search("anything at all", cell(tenant)) == []
