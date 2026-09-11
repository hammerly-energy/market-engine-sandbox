"""W2: the editor, served from the same process as the engine.

What is asserted here is the seam, not the interaction -- a drag cannot be
tested from pytest. The one thing that CAN fail silently on this side is
route ordering: StaticFiles is mounted at "/" and catches every path, so a
mount registered before /clear would shadow the API and the failure would
look like a frontend bug for an afternoon.
"""

import json
import math
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api import bounds
from src.api.app import app
from src.ingest.scenario import load_config, scenario_from_config
from src.model.clearing import clear


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


# --------------------------------------------------------------------- W2.1
# The editor's state is the single source of truth the eight levers mutate,
# and it is seeded from web/data/case5.json. That file is configs/w1.yaml
# restated as JSON, which is a SECOND COPY of a scenario -- the one thing in
# this phase that can rot silently. A copy that drifts would put the page on a
# network no test in this repo prices, so the copy is asserted rather than
# trusted, the same way configs/w1.yaml's duplication of m4's network is.
#
# What cannot be asserted from pytest is the JavaScript: there is no node in
# this environment and adding one would be a build step, which web/ exists
# without. So toConfig()'s round trip is checked at W2.8 through the HTTP
# surface, and what is checked here is the data the emitter reads.

SEED = Path("web/data/case5.json")
W1_CONFIG = Path("configs/w1.yaml")


def _resolve_inf(config):
    """The wire spelling of an unlimited line, back to a float.

    JSON has no infinity literal and configs/*.yaml writes .inf, so the seed
    carries "inf" -- the spelling bounds._limit already accepts.
    """
    out = json.loads(json.dumps(config))
    for spec in out["network"]["branches"].values():
        if spec["limit_mw"] == "inf":
            spec["limit_mw"] = math.inf
    return out


@pytest.fixture(scope="module")
def seed():
    return json.loads(SEED.read_text())


class TestTheSeedIsW1AndNotACopyThatDrifted:
    def test_the_network_is_w1s_network(self, seed):
        assert _resolve_inf(seed["config"])["network"] == load_config(W1_CONFIG)["network"]

    def test_the_fleet_is_w1s_fleet(self, seed):
        assert seed["config"]["fleet"] == load_config(W1_CONFIG)["fleet"]

    def test_the_load_is_w1s_load(self, seed):
        assert seed["config"]["load"] == load_config(W1_CONFIG)["load"]

    def test_the_seed_clears_to_w1s_prices(self, seed):
        """The point of the equality above, stated as prices.

        Field-for-field config equality is the cheap check; this is the one
        that would catch an equality test that had been loosened.
        """
        from_seed = clear(
            scenario_from_config(_resolve_inf(seed["config"]), origin="<seed>"),
            slack=seed["slack"],
        )
        from_yaml = clear(
            scenario_from_config(load_config(W1_CONFIG), origin="<w1>"),
            slack=load_config(W1_CONFIG)["network"]["slack"],
        )
        assert from_seed["lmp"] == from_yaml["lmp"]


class TestTheSeedCarriesWhatIsNotConfig:
    """Coordinates and the offer cap are in the seed but outside `config`,
    and the separation is the claim: bus x/y is editor state and never crosses
    the wire (CLAUDE.md assigns it to W2), and the cap is a market parameter
    the defaults policy reads rather than hardcodes."""

    def test_every_bus_has_coordinates(self, seed):
        assert set(seed["coords"]) == set(seed["config"]["network"]["buses"])

    def test_coordinates_are_not_in_the_config(self, seed):
        assert "coords" not in seed["config"]
        assert "coords" not in seed["config"]["network"]

    def test_the_offer_cap_is_the_value_firm_bids_carry(self, seed):
        # One number, not two. A cap in the market block that disagreed with
        # the bids would make "firm" mean something different per bid.
        values = {bid["value_usd_per_mwh"] for bid in seed["config"]["load"]["bids"].values()}
        assert values == {seed["market"]["offer_cap_usd_per_mwh"]}

    def test_the_recorded_slack_is_the_configs_slack(self, seed):
        # The editor posts slack explicitly; this asserts the two do not start
        # out disagreeing, which is what W2.6's dropdown then keeps true.
        assert seed["slack"] == seed["config"]["network"]["slack"]


class TestTheSeedIsServedAndPostable:
    def test_the_seed_is_served(self, client):
        r = client.get("/data/case5.json")
        assert r.status_code == 200
        assert r.json()["config"]["network"]["buses"] == ["A", "B", "C", "D", "E"]

    def test_the_seed_body_is_accepted_by_the_caps(self, seed):
        # The client-side bound check in state.js mirrors bounds.py, and this
        # asserts the thing both agree about: the seeded editor is inside
        # every cap before a visitor has touched anything.
        bounds.normalize(seed["config"])

    def test_the_seed_body_is_well_under_the_size_cap(self, seed):
        body = json.dumps({"config": seed["config"], "slack": seed["slack"], "limits": None})
        assert len(body.encode()) < bounds.MAX_BODY_BYTES

    def test_the_bid_cap_is_published(self, client):
        # state.js refuses a 41st bid before posting, which it can only do if
        # the cap is on the wire.
        assert client.get("/limits").json()["max_bids"] == bounds.MAX_BIDS
