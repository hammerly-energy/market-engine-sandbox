"""Shared fixtures.

One entry so far, and it exists because the deploy branch added the first
piece of state in this repo that outlives a single request.
"""

import pytest

from src.api import ratelimit


@pytest.fixture(autouse=True)
def fresh_rate_limiter():
    """A clean rate-limit table per test.

    The limiter counts per process and the suite is one process, all of whose
    requests arrive from the same test address. Without this, the 31st solve
    in any given minute is refused -- and it is refused by the deploy
    protection rather than by anything the test was written to check, so the
    failure reads as a broken engine.

    Rebinding the module attribute rather than clearing the table in place is
    what app.py's `ratelimit.limiter.check(...)` resolves at call time, and it
    leaves a test that installs its own limiter free to do so on top.
    """
    ratelimit.limiter = ratelimit.RateLimiter()
    yield
