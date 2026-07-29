"""Shared pytest fixtures. pytest auto-discovers this file -- any test file
can use the `warehouse` fixture just by naming it as an argument, no import
needed.
"""

import duckdb
import pytest

from build_warehouse import build_into


@pytest.fixture(scope="session")
def warehouse():
    """Builds one in-memory warehouse, shared by the entire test session
    (not just one file) -- the build is expensive on this machine (~250s,
    likely antivirus overhead on the Python process itself, not disk I/O),
    so every test file reuses this single instance instead of rebuilding."""
    con = duckdb.connect(":memory:")
    build_into(con)
    yield con
    con.close()
