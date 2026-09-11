"""W2: the editor, served from the same process as the engine.

What is asserted here is the seam, not the interaction -- a drag cannot be
tested from pytest. The one thing that CAN fail silently on this side is
route ordering: StaticFiles is mounted at "/" and catches every path, so a
mount registered before /clear would shadow the API and the failure would
look like a frontend bug for an afternoon.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


class TestTheMountDoesNotShadowTheApi:
    """The API answers even though "/" is mounted over everything."""

    def test_health_is_not_shadowed(self, client):
        assert client.get("/health").json() == {"status": "ok"}

    def test_limits_is_not_shadowed(self, client):
        assert client.get("/limits").json()["max_buses"] > 0

    def test_clear_is_not_shadowed(self, client):
        # A body the engine refuses still proves /clear was reached: a
        # shadowed route would 405 or return the index page instead.
        r = client.post("/clear", json={"config": {"fleet": {}}})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_scenario"


class TestThePageIsServed:
    def test_index_is_served_at_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")

    def test_modules_are_served_as_javascript(self, client):
        # An ES module served as text/plain is refused by the browser with a
        # MIME error and no other symptom.
        r = client.get("/js/api.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]

    def test_stylesheet_is_served(self, client):
        assert client.get("/css/style.css").status_code == 200

    def test_a_missing_asset_is_a_404_not_the_index(self, client):
        assert client.get("/js/not-a-file.js").status_code == 404


class TestScopeHonesty:
    """The site must not imply M5-M8 exist, and must say so in the reader's
    path rather than in a footer. This is a claim the page makes and it is
    cheap to let it rot, so it is asserted."""

    def test_the_scope_statement_is_in_the_page(self, client):
        # Collapsed, because the sentence wraps in the source and a line
        # break inside it is not a change to what the page says.
        body = " ".join(client.get("/").text.lower().split())
        assert "no unit commitment" in body
        assert "no storage" in body
        assert "no reserves" in body
