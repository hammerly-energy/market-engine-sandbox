r"""The per-IP rate limit that a public deploy adds.

W0 capped the SIZE of one body. It did not cap how many bodies arrive, and
`_read_capped`'s own docstring says so -- it names a reverse proxy as the
thing that would. A deploy of this repo has no reverse proxy of its own, so
`src/api/ratelimit.py` is that cap, and this file is what keeps it honest.

Two properties matter and they pull against each other. The limit has to
actually refuse a loop, and it has to not refuse a person. A test that only
asserted the first would pass on a limiter stuck at zero.

The limiter is time-based, so every test here injects `now` rather than
sleeping. A suite that sleeps a minute to prove a one-minute window is a suite
nobody runs.
"""

import pytest
from fastapi.testclient import TestClient

from src.api import ratelimit
from src.api.app import app
from src.api.bounds import BadRequest


@pytest.fixture
def limiter():
    return ratelimit.RateLimiter(max_calls=3, window_s=60.0)


class TestTheWindow:
    """Invariants of the limiter itself, independent of HTTP."""

    def test_it_allows_up_to_the_limit(self, limiter):
        for i in range(3):
            limiter.check("1.2.3.4", now=100.0 + i)

    def test_and_refuses_the_one_after(self, limiter):
        for i in range(3):
            limiter.check("1.2.3.4", now=100.0 + i)
        with pytest.raises(BadRequest) as caught:
            limiter.check("1.2.3.4", now=103.0)
        assert caught.value.status == 429
        assert caught.value.code == "rate_limited"

    def test_the_refusal_says_when_to_come_back(self, limiter):
        for i in range(3):
            limiter.check("1.2.3.4", now=100.0 + i)
        with pytest.raises(BadRequest) as caught:
            limiter.check("1.2.3.4", now=103.0)
        assert "try again in" in caught.value.detail

    def test_one_address_does_not_spend_another_s_allowance(self, limiter):
        for i in range(3):
            limiter.check("1.2.3.4", now=100.0 + i)
        limiter.check("5.6.7.8", now=103.0)

    def test_the_window_slides_rather_than_resetting(self, limiter):
        """A fixed window would allow 2x the rate across its boundary.

        Three calls at t=100, 101, 102 fill the allowance. At t=160.5 the
        cutoff is 100.5, so only the first has aged out and exactly one slot
        is free -- not all three, which is what a reset would give.
        """
        for i in range(3):
            limiter.check("1.2.3.4", now=100.0 + i)

        limiter.check("1.2.3.4", now=160.5)
        with pytest.raises(BadRequest):
            limiter.check("1.2.3.4", now=160.6)

    def test_the_table_cannot_grow_without_limit(self):
        """Forged X-Forwarded-For values must not become an allocation."""
        small = ratelimit.RateLimiter(max_calls=3, window_s=60.0, max_tracked=10)
        for i in range(500):
            small.check(f"10.0.0.{i}", now=100.0)
        assert len(small._hits) <= 10


class TestTheAddress:
    """Which caller a hit is counted against."""

    def test_the_first_forwarded_hop_wins(self):
        request = _FakeRequest({"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, "10.0.0.1")
        assert ratelimit.client_ip(request) == "9.9.9.9"

    def test_and_the_socket_is_the_fallback(self):
        assert ratelimit.client_ip(_FakeRequest({}, "10.0.0.1")) == "10.0.0.1"

    def test_a_blank_header_does_not_become_a_shared_bucket(self):
        """'' would key every caller to one bucket and lock them out together."""
        assert ratelimit.client_ip(_FakeRequest({"x-forwarded-for": ""}, "7.7.7.7")) == "7.7.7.7"


class TestThroughHTTP:
    """The limit as a caller meets it."""

    @pytest.fixture
    def client(self, monkeypatch):
        monkeypatch.setattr(
            ratelimit, "limiter", ratelimit.RateLimiter(max_calls=2, window_s=60.0)
        )
        return TestClient(app)

    def test_the_cap_is_published(self, client):
        """A client can pace itself rather than discovering the limit by 429."""
        assert client.get("/limits").json()["max_solves_per_minute"] == 2

    def test_a_flood_gets_a_named_429(self, client):
        body = {"config": _tiny_config()}
        assert client.post("/clear", json=body).status_code == 200
        assert client.post("/clear", json=body).status_code == 200

        refused = client.post("/clear", json=body)
        assert refused.status_code == 429
        assert refused.json()["error"] == "rate_limited"

    def test_liveness_is_not_rate_limited(self, client):
        """/health must answer while /clear is refusing, or a host kills the box."""
        body = {"config": _tiny_config()}
        for _ in range(4):
            client.post("/clear", json=body)
        assert client.get("/health").status_code == 200

    def test_the_refusal_costs_no_solve(self, client, monkeypatch):
        """Rejecting after solving would spend exactly what the cap protects."""
        body = {"config": _tiny_config()}
        client.post("/clear", json=body)
        client.post("/clear", json=body)

        def explode(*args, **kwargs):
            raise AssertionError("a rate-limited request reached the solver")

        monkeypatch.setattr("src.api.app.clear", explode)
        assert client.post("/clear", json=body).status_code == 429


class _FakeRequest:
    def __init__(self, headers, host):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def _tiny_config():
    """The smallest scenario this engine will price.

    Two buses and a branch, because one bus is refused -- "nodal clearing
    needs a network" -- and a rate-limit test wants the cheapest solve that is
    still a real one, not the cheapest body.
    """
    return {
        "name": "rate-limit-fixture",
        "network": {
            "slack": "A",
            "buses": ["A", "B"],
            "branches": {
                "AB": {"from": "A", "to": "B", "reactance_pu": 0.03, "limit_mw": None}
            },
        },
        "fleet": {"A1": {"bus": "A", "cost_usd_per_mwh": 10.0, "pmax_mw": 100.0}},
        "load": {
            "source": "blocks",
            "shape": [1.0],
            "bids": {
                "B_firm": {"bus": "B", "peak_mw": 50.0, "value_usd_per_mwh": 5000.0}
            },
        },
    }
