"""Scenario scripts. Run from the memory_demo folder, for example:

    .venv/Scripts/python.exe -m scenarios.s2_retrieval --backend both
"""
import sys
from pathlib import Path

# Lets `python -m scenarios.xxx` find the nineone_mem package under src/.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
