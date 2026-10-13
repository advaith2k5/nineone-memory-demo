"""Gemini chat + embeddings, with the protections the free tier needs.

What lives here:
- CallCounter: counts every live Gemini call so each run can print its cost.
- get_chat_model(): a LangChain chat model with a rate limiter and retries.
- NormalizedEmbeddings: Gemini embeddings cut to 768 numbers AND made length 1.0, with its own
  rate limiter and retry (embedding calls come in bursts and hit a per-minute limit).
"""
import math
import threading
import time

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.embeddings import Embeddings
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from . import config


class CallCounter(BaseCallbackHandler):
    """Counts live calls so we can print "this run used N Gemini calls"."""

    def __init__(self) -> None:
        self.chat_calls = 0
        self.embed_calls = 0
        self._lock = threading.Lock()

    def on_chat_model_start(self, *args, **kwargs):
        with self._lock:
            self.chat_calls += 1

    def on_llm_start(self, *args, **kwargs):
        with self._lock:
            self.chat_calls += 1

    def count_chat(self) -> None:
        # For libraries that call Gemini themselves (Mem0) and so skip the LangChain callback.
        with self._lock:
            self.chat_calls += 1

    def summary(self) -> str:
        return f"Gemini calls this run: chat={self.chat_calls}, embedding={self.embed_calls}"


COUNTER = CallCounter()

# One shared limiter, so the agent and the memory libraries share the same budget.
_RATE_LIMITER = InMemoryRateLimiter(
    requests_per_second=config.MAX_REQUESTS_PER_SECOND,
    check_every_n_seconds=0.1,
    max_bucket_size=1,
)


# Embeddings are limited separately from chat. A full test run hit "429 RESOURCE_EXHAUSTED" with no
# limiter at all, and it cleared after about a minute, so this is a per-minute burst limit.
_EMBED_LIMITER = InMemoryRateLimiter(
    requests_per_second=config.MAX_EMBED_REQUESTS_PER_SECOND,
    check_every_n_seconds=0.05,
    max_bucket_size=3,
)
_RETRYABLE = ("RESOURCE_EXHAUSTED", "429", "UNAVAILABLE", "503")   # words in Google's error text


def _call_with_retry(fn, attempts: int = 5):
    """Run fn(). On a "too many requests" or "overloaded" error wait and try again (2s, 4s, 8s, 16s).

    Any other error is raised at once: retrying a real bug only hides it. If the DAILY quota is gone,
    every attempt fails and the last error is raised after about 30 seconds.
    """
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i == attempts - 1 or not any(w in str(e) for w in _RETRYABLE):
                raise
            time.sleep(2 ** (i + 1))


def wait_for_chat_slot() -> None:
    """Block until the shared rate limiter allows one more chat call, then count it."""
    _RATE_LIMITER.acquire(blocking=True)
    COUNTER.count_chat()


def get_chat_model(model: str | None = None) -> ChatGoogleGenerativeAI:
    """Chat model. temperature=0 so the same input gives (nearly) the same answer."""
    if not config.GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY is empty. Put it in memory_demo/.env")
    return ChatGoogleGenerativeAI(
        model=model or config.AGENT_MODEL,
        google_api_key=config.GOOGLE_API_KEY,
        temperature=0,
        max_retries=config.LLM_MAX_RETRIES,
        timeout=config.LLM_TIMEOUT_SECONDS,
        rate_limiter=_RATE_LIMITER,
        callbacks=[COUNTER],
    )


def normalize(vec: list[float]) -> list[float]:
    """Scale a vector to length 1.0. Google only does this for the full 3072 size."""
    length = math.sqrt(sum(v * v for v in vec))
    if length == 0:
        raise ValueError("Embedding came back as all zeros")
    return [v / length for v in vec]


class NormalizedEmbeddings(Embeddings):
    """Gemini embeddings: 768 numbers, length 1.0, so cosine scores are honest."""

    def __init__(self, inner=None) -> None:
        # `inner` can be replaced in tests (a fake that fails on purpose).
        self._inner = inner or GoogleGenerativeAIEmbeddings(
            model=f"models/{config.EMBED_MODEL}",
            google_api_key=config.GOOGLE_API_KEY,
            output_dimensionality=config.EMBED_DIMS,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        _EMBED_LIMITER.acquire(blocking=True)
        COUNTER.embed_calls += 1
        out = [normalize(v) for v in _call_with_retry(lambda: self._inner.embed_documents(texts))]
        self._check_size(out[0])
        return out

    def embed_query(self, text: str) -> list[float]:
        _EMBED_LIMITER.acquire(blocking=True)
        COUNTER.embed_calls += 1
        v = normalize(_call_with_retry(lambda: self._inner.embed_query(text)))
        self._check_size(v)
        return v

    @staticmethod
    def _check_size(v: list[float]) -> None:
        # If this ever differs from the pgvector column size, searches break
        # silently. Fail loudly instead.
        if len(v) != config.EMBED_DIMS:
            raise RuntimeError(f"Embedding has {len(v)} numbers, expected {config.EMBED_DIMS}")
