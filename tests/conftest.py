"""Runs once at the start of every test session.

Several tests rely on the demo data being exactly as the seed script makes it: 90 ledger rows, 86 of one
finding type with 62 held, "7 of 9" on site TOK-104. If an earlier run was killed halfway (for example
test_e2e stopped before its cleanup), an extra row could be left behind and break unrelated tests.
Reseeding at the start removes that whole class of failure.

It only touches mock.* and ledger.outcomes. Memory stores are not touched: every test uses its own tenant.
"""
import pytest

from nineone_mem.seed.mock_data import seed


@pytest.fixture(scope="session", autouse=True)
def fresh_demo_data():
    seed()
