"""Live checks for src/nineone_mem/llm.py. Total Gemini calls: 1 chat + 1 embedding.

Run:  .venv/Scripts/python.exe -m pytest tests/test_llm.py -v -s
"""
import math

import pytest

from nineone_mem import config
from nineone_mem.llm import COUNTER, NormalizedEmbeddings, get_chat_model, normalize


def test_normalize_gives_length_one_offline():
    # No API call. Edge case: a zero vector must fail loudly, not divide by zero silently.
    v = normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(x * x for x in v)), 1.0)
    with pytest.raises(ValueError):
        normalize([0.0, 0.0])


@pytest.mark.live
def test_embeddings_are_768_and_length_one():
    emb = NormalizedEmbeddings()
    vecs = emb.embed_documents(
        ["RNA1301000057_1 accessibility dropped after tilt change"]
    )
    assert len(vecs) == 1
    assert len(vecs[0]) == config.EMBED_DIMS == 768
    assert math.isclose(math.sqrt(sum(x * x for x in vecs[0])), 1.0, abs_tol=1e-6)


@pytest.mark.live
def test_chat_answers_and_counter_counts():
    before = COUNTER.chat_calls
    reply = get_chat_model().invoke("Reply with exactly one word: pong")
    # reply.content can be a LIST of blocks with this Gemini wrapper; .text is always a string.
    # We do NOT check the exact word: flash-lite answered "Ping" twice when asked for "pong".
    # This test checks the plumbing (a call went out, text came back, the counter moved).
    assert len(reply.text.strip()) > 0
    assert COUNTER.chat_calls == before + 1
    print("\n" + COUNTER.summary())


def test_a_used_run_id_is_detected_and_a_fresh_one_is_not():
    # run_case refuses a run id that already has checkpoints, so a new case never continues an old thread.
    import uuid
    import psycopg
    from langgraph.checkpoint.base import empty_checkpoint
    from langgraph.checkpoint.postgres import PostgresSaver
    from nineone_mem import config
    from nineone_mem.agent.build import _run_id_already_used

    thread = f"checkpoint_test_{uuid.uuid4().hex}"
    with PostgresSaver.from_conn_string(config.DATABASE_URL) as saver:
        saver.setup()
        assert _run_id_already_used(thread) is False                       # fresh id
        saver.put({"configurable": {"thread_id": thread, "checkpoint_ns": ""}}, empty_checkpoint(),
                  {"source": "input", "step": 0, "parents": {}}, {})       # save one real checkpoint under it
        assert _run_id_already_used(thread) is True                        # now it counts as used
    with psycopg.connect(config.DATABASE_URL) as conn:                     # tidy up the rows we made
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            conn.execute(f"DELETE FROM {table} WHERE thread_id=%s", (thread,))


def test_embeddings_retry_on_a_rate_limit_error_but_not_on_a_real_bug():
    # Offline: a fake inner client. The first two calls fail with the real Google error text, the third works.
    import pytest
    from unittest import mock
    from nineone_mem import config
    from nineone_mem.llm import NormalizedEmbeddings

    class Flaky:
        def __init__(self, fail_times, error): self.n, self.fail_times, self.error = 0, fail_times, error
        def embed_query(self, text):
            self.n += 1
            if self.n <= self.fail_times:
                raise RuntimeError(self.error)
            return [3.0] + [0.0] * (config.EMBED_DIMS - 1)

    with mock.patch("nineone_mem.llm.time.sleep") as sleeps:            # do not actually wait
        flaky = Flaky(2, "429 RESOURCE_EXHAUSTED. Please try again later.")
        v = NormalizedEmbeddings(inner=flaky).embed_query("x")
        assert flaky.n == 3 and v[0] == 1.0                              # retried twice, then normalized
        # The patch also catches the rate limiter's own tiny polling sleeps, so keep only the retry waits.
        assert [c.args[0] for c in sleeps.call_args_list if c.args[0] >= 1] == [2, 4]      # waited 2s then 4s

        bug = Flaky(5, "ValueError: bad request body")
        with pytest.raises(RuntimeError):
            NormalizedEmbeddings(inner=bug).embed_query("x")
        assert bug.n == 1                                                # a real bug is NOT retried
