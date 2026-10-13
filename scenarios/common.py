"""Small helpers shared by every scenario: make a backend by name, fresh tenants, and printing."""
from __future__ import annotations

import argparse
import uuid

from nineone_mem.llm import COUNTER
from nineone_mem.memory.langmem_backend import LangMemBackend
from nineone_mem.memory.mem0_backend import Mem0Backend

BACKENDS = {"langmem": LangMemBackend, "mem0": Mem0Backend}


def make_backend(name: str):
    return BACKENDS[name]()


def new_tenant(prefix: str = "t") -> str:
    # A fresh tenant per run = a clean, isolated memory. Nothing to clean up afterwards.
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def parse_backends(description: str, argv=None) -> list[str]:
    p = argparse.ArgumentParser(description=description)
    p.add_argument("--backend", choices=["langmem", "mem0", "both"], default="both")
    choice = p.parse_args(argv).backend
    return list(BACKENDS) if choice == "both" else [choice]


def banner(text: str) -> None:
    print("\n" + "=" * 78 + f"\n{text}\n" + "=" * 78)


def sub(text: str) -> None:
    print(f"\n--- {text}")


def short(text: str, n: int = 95) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 3] + "..."


def calls() -> str:
    return COUNTER.summary()
