"""Put the demo data back to its starting state, and clear the rows that tests and scenarios leave behind.

What it clears:   ran.agent_evidence, ran.memory_candidates, ran.memory_history
What it reseeds:  mock.pm_kpi, mock.fm_alarm, mock.cm_change, ledger.outcomes   (via nineone_mem.seed.mock_data)
What it does NOT touch: the LangMem and Mem0 memory stores, and LangGraph checkpoints. Each run uses its own
tenant and run id, so old rows there cannot affect new runs. To wipe those too, remove the Docker volume
(`docker compose down -v`) and start again.

Run:  .venv/Scripts/python.exe scripts/reset_demo_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import psycopg  # noqa: E402

from nineone_mem import config  # noqa: E402
from nineone_mem.seed.mock_data import seed  # noqa: E402


def main() -> None:
    with psycopg.connect(config.DATABASE_URL) as conn:
        conn.execute("TRUNCATE ran.agent_evidence, ran.memory_candidates, ran.memory_history RESTART IDENTITY")
    print("ledger after reseed (finding_type: total, held):", seed())


if __name__ == "__main__":
    main()
