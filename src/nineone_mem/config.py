"""All the settings in one place. Change a model name here and nothing else.

Why these values (checked by real test calls on 2026-10-13):
- gemini-3.1-flash-lite answered and did tool-calling correctly.
- gemini-3.5 / 3.6 / 3.7 / 3.8 flash were overloaded (503) or hung, gemini-2.5-flash
  is closed to new users (404). To retry a bigger model later, run
  scripts/test_agent_model.py <model-name>, then change AGENT_MODEL below.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # the memory_demo/ folder


def _load_env() -> None:
    """Read memory_demo/.env into os.environ (existing variables win)."""
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


_load_env()

# Mem0 sends anonymous usage stats to PostHog unless told not to. It reads this switch
# ONCE when it is first imported, so it must be set here, before any `import mem0`.
# Forced (not setdefault) on purpose: nothing from this project should leave the machine
# except the Gemini calls.
os.environ["MEM0_TELEMETRY"] = "False"

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://nineone:nineone@localhost:5433/nineone_mem")

# Which model does what. Both are the same for now (see top of file).
AGENT_MODEL = "gemini-3.1-flash-lite"       # the RCA agent's reasoning
MEMORY_MODEL = "gemini-3.1-flash-lite"      # Mem0 / LangMem extraction + conflict decisions
EMBED_MODEL = "gemini-embedding-001"

# 768 numbers per memory. The default is 3072, but pgvector's fast index (HNSW)
# stops at 2000, so 3072 would silently fall back to slow scans.
EMBED_DIMS = 768

# Free-tier protection. Google does not publish exact limits, so we are careful.
MAX_REQUESTS_PER_SECOND = 0.25   # one chat call every 4 seconds, at most
# Embeddings have their own per-minute limit (a full test run hit "429 RESOURCE_EXHAUSTED" on 13 Oct and
# it cleared after about a minute). 1.5 per second is 90 per minute, under the 100/min we expect.
MAX_EMBED_REQUESTS_PER_SECOND = 1.5
LLM_MAX_RETRIES = 4              # for 429 (limit) and 503 (overloaded)
LLM_TIMEOUT_SECONDS = 60

# v3 section 6.3: below this many cases a track record is forced to "neutral".
SAMPLE_FLOOR = 30

TENANT = "tenantA"   # the one fake customer used in every scenario
