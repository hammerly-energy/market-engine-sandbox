"""W2: the editor, served from the same process as the engine.

What is asserted here is the seam, not the interaction -- a drag cannot be
tested from pytest. The one thing that CAN fail silently on this side is
route ordering: StaticFiles is mounted at "/" and catches every path, so a
mount registered before /clear would shadow the API and the failure would
look like a frontend bug for an afternoon.
"""

import json
import math
import re
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
# without. So toConfig()'s round trip runs in a browser -- web/check-emit.html,
# W2.8 -- and what is checked here is the data the emitter reads. The two meet
# at this file: the emitter is asserted to reproduce the seed, and the seed is
# asserted below to be w1.yaml.

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


# --------------------------------------------------------------------- W2.2
# Transport. postClear(state), request coalescing by monotonic id, and one
# error surface that switches on the stable code and prints the detail
# verbatim.
#
# The coalescing itself cannot be tested from pytest -- it is JavaScript, and
# there is no node in this environment. What CAN rot here, silently and
# expensively, is the contract between the two halves: the frontend branches
# on `code`, and bounds.py owns the list of codes. A refusal added on the
# server with no branch on the client renders as a bare code with no heading
# and no advice, and nothing anywhere would say so.
#
# So the surface is asserted against the server BEHAVIOURALLY: each body
# below is one this server refuses, and the code it answers with must be one
# web/js/errors.js knows. Provoked over HTTP rather than grepped out of
# bounds.py, so a code that moves between modules is still covered.

ERRORS_JS = Path("web/js/errors.js")


def _known_codes():
    """The codes web/js/errors.js has a branch for.

    Parsed rather than imported, because there is no JavaScript runtime here.
    The table is a flat object literal of `code: {` entries, so this reads it
    the only way Python can and would fail loudly if it stopped being one.
    """
    entries = re.findall(r"^  ([a-z_][a-z0-9_]*): \{", ERRORS_JS.read_text(), re.M)
    assert entries, "no codes parsed out of errors.js -- the table changed shape"
    return set(entries)


def _too_many(seed, what, n):
    """A config over one cap, built from the seed so nothing else is wrong."""
    config = json.loads(json.dumps(seed["config"]))
    if what == "buses":
        config["network"]["buses"] = [f"b{i}" for i in range(n)]
    elif what == "branches":
        config["network"]["branches"] = {
            f"x{i}": {"from": "A", "to": "B", "reactance_pu": 0.03, "limit_mw": "inf"}
            for i in range(n)
        }
    elif what == "generators":
        config["fleet"] = {
            f"g{i}": {"bus": "A", "cost_usd_per_mwh": 25.0, "pmax_mw": 100.0}
            for i in range(n)
        }
    elif what == "bids":
        config["load"]["bids"] = {
            f"d{i}": {"bus": "B", "peak_mw": 1.0, "value_usd_per_mwh": 5000.0}
            for i in range(n)
        }
    elif what == "hours":
        config["load"]["shape"] = [1.0] * n
    return config


class TestTheErrorSurfaceKnowsEveryCodeTheServerEmits:
    """Every refusal this server can answer with has a branch in errors.js.

    A missing branch is not a crash -- describe() falls back to the code as
    its own heading -- which is exactly why it needs a test. It would ship as
    a visitor reading `too_many_bids` where a sentence belonged.
    """

    def test_a_malformed_body_is_a_known_code(self, client):
        r = client.post("/clear", content=b"{not json", headers={"content-type": "application/json"})
        assert r.json()["error"] == "malformed_json"
        assert "malformed_json" in _known_codes()

    def test_an_oversized_body_is_a_known_code(self, client):
        r = client.post(
            "/clear",
            content=b'{"config":"' + b"x" * (bounds.MAX_BODY_BYTES + 1) + b'"}',
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 413
        assert r.json()["error"] == "body_too_large"
        assert "body_too_large" in _known_codes()

    def test_a_scenario_the_engine_refuses_is_a_known_code(self, client, seed):
        # A slack that is not a bus: an assertion by the caller, and the check
        # that catches the editor letting its dropdown drift (W2.6).
        r = client.post("/clear", json={"config": seed["config"], "slack": "Z"})
        assert r.json()["error"] == "invalid_scenario"
        assert "Z" in r.json()["detail"]  # the detail names the bus, so it is shown as sent
        assert "invalid_scenario" in _known_codes()

    def test_a_forbidden_load_source_is_a_known_code(self, client, seed):
        config = json.loads(json.dumps(seed["config"]))
        config["load"]["source"] = "eia930"
        r = client.post("/clear", json={"config": config})
        assert r.json()["error"] == "unsupported_load_source"
        assert "unsupported_load_source" in _known_codes()

    @pytest.mark.parametrize(
        "what, n",
        [
            ("buses", bounds.MAX_BUSES + 1),
            ("branches", bounds.MAX_BRANCHES + 1),
            ("generators", bounds.MAX_GENERATORS + 1),
            ("bids", bounds.MAX_BIDS + 1),
            ("hours", bounds.MAX_HOURS + 1),
        ],
    )
    def test_every_cap_refusal_is_a_known_code(self, client, seed, what, n):
        r = client.post("/clear", json={"config": _too_many(seed, what, n)})
        assert r.json()["error"] == f"too_many_{what}"
        assert f"too_many_{what}" in _known_codes()

    def test_an_unclearable_market_is_a_known_code(self, client):
        """Inelastic load the fleet cannot serve.

        Unreachable from the editor -- toConfig() always emits blocks, and a
        priced demand side cannot be infeasible on capacity -- but reachable
        over HTTP, so the surface must still name it.
        """
        r = client.post(
            "/clear",
            json={
                "config": {
                    "name": "short",
                    "network": {"slack": "A", "buses": ["A", "B"],
                                "branches": {"AB": {"from": "A", "to": "B",
                                                    "reactance_pu": 0.03, "limit_mw": "inf"}}},
                    "fleet": {"g": {"bus": "A", "cost_usd_per_mwh": 10.0, "pmax_mw": 1.0}},
                    "load": {"source": "static", "mw": {"B": 500.0}},
                },
                "slack": "A",
            },
        )
        assert r.json()["error"] == "solve_failed"
        assert "solve_failed" in _known_codes()

    def test_the_client_only_codes_are_there_too(self):
        """Failures with no server to name them still get a sentence.

        A fetch that never reached a response is not a statement about the
        body, so it does not borrow one of the server's codes -- and the one
        surface still has to render it.
        """
        assert {"unreachable", "unreadable_response", "client_error", "unknown_error"} <= _known_codes()


class TestWhatTheEditorPostsComesBackPriced:
    """The seed, posted as the editor posts it, over HTTP.

    W0 asserts the HTTP result matches the in-process one field for field.
    What this adds is the body the EDITOR sends -- config, an explicit slack,
    and null limits -- and the fields main.js reads off the response.
    """

    @pytest.fixture(scope="class")
    def cleared(self, client, seed):
        r = client.post(
            "/clear",
            json={"config": seed["config"], "slack": seed["slack"], "limits": None},
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_the_engine_reports_the_slack_it_used(self, cleared, seed):
        assert cleared["slack"] == seed["slack"]

    def test_one_island_and_it_is_named_by_its_slack(self, cleared, seed):
        assert list(cleared["islands"]) == [seed["slack"]]

    def test_the_series_the_page_reads_are_all_there(self, cleared):
        assert len(cleared["hours"]) == 24
        assert set(cleared["lmp"]) == set(cleared["buses"])
        assert set(cleared["flows"]) == set(cleared["lines"])
        assert set(cleared["dispatch"]) == set(cleared["generators"])

    def test_an_explicit_null_limits_is_not_an_override(self, client, seed):
        """toLimits() emits null, not {}, for an untouched editor.

        Both mean "the scenario's own ratings", and the two must not be able
        to price differently -- otherwise the posted body's readability would
        be a market decision.
        """
        with_null = client.post(
            "/clear", json={"config": seed["config"], "slack": seed["slack"], "limits": None}
        ).json()
        with_empty = client.post(
            "/clear", json={"config": seed["config"], "slack": seed["slack"], "limits": {}}
        ).json()
        assert with_null["lmp"] == with_empty["lmp"]


class TestTheTransportModulesAreServed:
    def test_errors_is_served_as_javascript(self, client):
        r = client.get("/js/errors.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]

    def test_render_is_served_as_javascript(self, client):
        r = client.get("/js/render.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]


class TestTheRenderHasEveryNumberItNeeds:
    """W2.3 draws the network and prints three readouts. Each one is a field
    of the clear() return, indexed -- never assembled in the browser.

    What can fail silently here is ALIGNMENT. Every series is one array per
    name, read positionally against "hours"; a series a hour shorter than
    "hours" would print the wrong hour's price with no error anywhere, which
    is the failure the wire format exists to prevent and therefore the one
    worth asserting on the page's behalf.
    """

    @pytest.fixture(scope="class")
    def cleared(self, client, seed):
        r = client.post(
            "/clear",
            json={"config": seed["config"], "slack": seed["slack"], "limits": None},
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_lmp_per_bus_is_aligned_to_hours(self, cleared):
        n = len(cleared["hours"])
        assert all(len(series) == n for series in cleared["lmp"].values())

    def test_lambda_is_keyed_by_island_and_aligned_to_hours(self, cleared):
        """Never a bare array. A shape that changed with the topology is a
        shape the frontend would have to branch on, and it would branch wrong
        the first time someone cut a line."""
        n = len(cleared["hours"])
        assert set(cleared["lmbda"]) == set(cleared["islands"])
        assert all(len(series) == n for series in cleared["lmbda"].values())

    def test_the_residual_is_per_island_and_per_hour(self, cleared):
        """Summing either dimension would let a positive residual cancel a
        negative one, so the page reads one number per island per hour."""
        n = len(cleared["hours"])
        assert set(cleared["settlement"]) == set(cleared["islands"])
        for ledger in cleared["settlement"].values():
            assert len(ledger["residual"]) == n

    def test_the_residual_the_page_prints_is_zero_in_every_hour(self, cleared):
        """The claim the whole repo rests on, asserted at the page's own
        boundary: what renderIslands puts on screen is ~0, hour by hour."""
        for ledger in cleared["settlement"].values():
            assert all(abs(r) < 1e-6 for r in ledger["residual"])

    def test_lambda_is_the_lmp_at_the_slack(self, cleared):
        """Why an island is named by its slack, asserted rather than assumed.
        The page prints the name next to the number and the two must mean the
        same thing."""
        for home, series in cleared["lmbda"].items():
            assert series == pytest.approx(cleared["lmp"][home])

    def test_every_bus_the_map_draws_has_a_price(self, cleared, seed):
        """The map is drawn from editor state and the prices come from the
        response. They are keyed the same, so the readout cannot list a bus
        the picture does not show."""
        assert set(cleared["lmp"]) == set(seed["config"]["network"]["buses"])


# --------------------------------------------------------------------- W2.4
# The five levers that are not a drag: line limit, peak load, generator
# capacity, generator offer, and the hour.
#
# Four of them change the scenario and are answered by a solve. THE HOUR IS
# NOT, and that is the phase: clear() returns the whole day, so the hour is an
# index into an answer already in the browser. What can rot silently is the
# alignment between what the slider can reach and what the response carries --
# a slider whose top is 24 against a response of 12 hours prints `undefined`
# where a price belongs, with no error anywhere.
#
# The sliders themselves are JavaScript and there is no runtime here, so what
# is asserted is (1) the engine's half of each lever, provoked over HTTP the
# way the editor provokes it, and (2) the slider DOMAINS, parsed out of
# controls.js -- because a domain that cannot represent the seed silently
# clamps or snaps the scenario the first time a visitor touches it.

CONTROLS_JS = Path("web/js/controls.js")


def _js_const(name):
    """A numeric `const NAME = 123;` out of controls.js.

    Parsed rather than imported, for the same reason _known_codes is: there is
    no JavaScript runtime in this environment. Fails loudly if the constant
    stops being a plain number, which is the only way it could move without
    this noticing.
    """
    m = re.search(rf"^const {name} = (-?[\d.]+);", CONTROLS_JS.read_text(), re.M)
    assert m, f"{name} is not a plain numeric const in controls.js"
    return float(m.group(1))


def _post(client, seed, **over):
    body = {"config": seed["config"], "slack": seed["slack"], "limits": None}
    config = json.loads(json.dumps(seed["config"]))
    body["config"] = config
    for key, value in over.items():
        if key == "limits":
            body["limits"] = value
        elif key == "fleet":
            for gen, fields in value.items():
                config["fleet"][gen].update(fields)
        elif key == "bids":
            for bid, fields in value.items():
                config["load"]["bids"][bid].update(fields)
        else:
            raise AssertionError(key)
    r = client.post("/clear", json=body)
    assert r.status_code == 200, r.text
    return r.json()


class TestTheLineLimitLeverIsAnArgumentAndNotAConfigEdit:
    """clear() takes limits as its own argument, so the slider moves a rating
    without rewriting the scenario the rating belongs to. That is what makes
    dropping the override restore the original exactly -- and it is why
    toLimits() may emit null rather than having to remember what it replaced.
    """

    def test_the_override_changes_the_price(self, client, seed):
        # DE is rated 240 MW and binds in case5. Squeezing it must move a
        # price, or the lever is wired to nothing.
        base = _post(client, seed)
        tight = _post(client, seed, limits={"DE": 100.0})
        assert tight["lmp"] != base["lmp"]

    def test_the_engine_reports_the_rating_it_used(self, client, seed):
        """The readout beside the slider is the slider's own position, but
        the rating the market was cleared against comes back on the wire --
        so a lever that failed to reach the engine is visible rather than
        merely believed."""
        tight = _post(client, seed, limits={"DE": 100.0})
        assert tight["limits"]["DE"] == 100.0

    def test_the_unlimited_notch_unbinds_the_line(self, client, seed):
        """The top of the slider writes null, which crosses as "inf".

        Not a large finite number: an unrated line is what the scenario says,
        and a 1000 MW line that happens never to bind is a different claim.
        With no rating, mu on that line is zero in every hour.
        """
        opened = _post(client, seed, limits={"DE": "inf"})
        assert opened["limits"]["DE"] is None  # wire spelling of infinity
        assert all(m == 0.0 for m in opened["mu"]["DE"])

    def test_dropping_the_override_restores_the_scenario_exactly(self, client, seed):
        base = _post(client, seed)
        _post(client, seed, limits={"DE": 100.0})
        assert _post(client, seed, limits=None)["lmp"] == base["lmp"]


class TestTheGeneratorLevers:
    def test_zero_capacity_stops_the_unit(self, client, seed):
        out = _post(client, seed, fleet={"E1": {"pmax_mw": 0.0}})
        assert all(p == 0.0 for p in out["dispatch"]["E1"])

    def test_capacity_comes_back_on_the_wire(self, client, seed):
        """gen_pmax and gen_cost are returned, so the merit-order stack of W3
        can be drawn without the browser holding a second copy of the fleet."""
        out = _post(client, seed, fleet={"E1": {"pmax_mw": 250.0}})
        assert out["gen_pmax"]["E1"] == 250.0

    def test_raising_an_offer_above_the_next_unit_reprices_the_market(self, client, seed):
        """E1 is the cheapest unit at $10. Offered above C1's $30
        it stops being the marginal resource anywhere, and a price moves."""
        base = _post(client, seed)
        dear = _post(client, seed, fleet={"E1": {"cost_usd_per_mwh": 35.0}})
        assert dear["gen_cost"]["E1"] == 35.0
        assert dear["lmp"] != base["lmp"]

    def test_an_offer_the_slider_can_reach_still_clears(self, client, seed):
        """The top of the offer slider, on every unit at once. It must price,
        not refuse -- a lever that can produce an error at its own end is a
        lever with an unreachable half."""
        top = _js_const("COST_MAX_USD")
        out = _post(
            client,
            seed,
            fleet={g: {"cost_usd_per_mwh": top} for g in seed["config"]["fleet"]},
        )
        assert all(abs(r) < 1e-6 for r in out["settlement"][seed["slack"]]["residual"])


class TestTheDemandLever:
    def test_a_bid_at_zero_asks_for_nothing(self, client, seed):
        out = _post(client, seed, bids={"D_firm": {"peak_mw": 0.0}})
        assert all(q == 0.0 for q in out["bid_mw"]["D_firm"])

    def test_every_bid_at_zero_is_degenerate_not_broken(self, client, seed):
        """All load zero: the engine solves and lambda sits at -0.0.

        CLAUDE.md lists this under what the engine already refuses as
        "degenerate, not broken". The slider's bottom end reaches it, so it is
        asserted rather than assumed.
        """
        out = _post(
            client, seed, bids={b: {"peak_mw": 0.0} for b in seed["config"]["load"]["bids"]}
        )
        assert all(p == 0.0 for p in out["dispatch"]["E1"])

    def test_more_load_than_the_fleet_can_serve_sheds_rather_than_refusing(
        self, client, seed
    ):
        """The editor emits only priced blocks, so scarcity is a price and not
        an error (W1). The demand slider is the most likely way a visitor
        reaches it, so this is the lever's real acceptance test."""
        cap = seed["market"]["offer_cap_usd_per_mwh"]
        top = _js_const("PEAK_MAX_MW")
        out = _post(
            client, seed, bids={b: {"peak_mw": top} for b in seed["config"]["load"]["bids"]}
        )
        peak = out["hours"][max(range(24), key=lambda t: out["bid_mw"]["D_firm"][t])]
        served = sum(out["served"][b][peak] for b in out["bids"])
        asked = sum(out["bid_mw"][b][peak] for b in out["bids"])
        assert served < asked  # shed
        assert max(out["lmp"][i][peak] for i in out["buses"]) == pytest.approx(cap)


class TestTheHourLeverNeedsNoSolve:
    """The hour indexes the day the last solve returned. It does not post.

    What that requires of the wire is that the day come back WHOLE and
    ALIGNED: every hour the slider can reach must exist in every series the
    page reads, or the slider prints undefined where a price belongs.
    """

    @pytest.fixture(scope="class")
    def cleared(self, client, seed):
        r = client.post(
            "/clear", json={"config": seed["config"], "slack": seed["slack"], "limits": None}
        )
        assert r.status_code == 200, r.text
        return r.json()

    def test_the_returned_day_is_as_long_as_the_shape_the_slider_spans(
        self, cleared, seed
    ):
        # The slider's max is state.shape.length. One post must answer all of
        # it; a shorter response is the silent failure this asserts away.
        assert len(cleared["hours"]) == len(seed["config"]["load"]["shape"])

    def test_every_series_the_hour_indexes_covers_every_hour(self, cleared):
        n = len(cleared["hours"])
        for field in ("lmp", "congestion", "flows", "mu", "dispatch", "served", "bid_mw"):
            assert all(len(s) == n for s in cleared[field].values()), field
        for ledger in cleared["settlement"].values():
            assert all(len(s) == n for s in ledger.values())

    def test_the_hours_differ_so_the_lever_has_something_to_show(self, cleared):
        """A day of identical hours would make the hour slider look broken
        and would also mean the shape never reached the LP."""
        assert len({tuple(round(cleared["lmp"][b][t], 6) for b in cleared["buses"])
                    for t in range(len(cleared["hours"]))}) > 1


class TestTheSliderDomainsCanRepresentTheSeed:
    """A domain is a market assumption, the same as a default.

    Each slider clamps its start position into its range and snaps to its
    step. So a seeded value outside a domain, or off its grid, would be
    silently rewritten the first time a visitor touched that slider -- the
    page would price a scenario the repo does not test, with nothing on
    screen saying so. Fixed domains, asserted against the fixed seed.
    """

    def test_every_finite_line_rating_fits_under_the_ceiling(self, seed):
        ceiling = _js_const("LIMIT_CEILING_MW")
        step = _js_const("LIMIT_STEP_MW")
        for name, spec in seed["config"]["network"]["branches"].items():
            if spec["limit_mw"] == "inf":
                continue  # the last notch, which is not a number
            assert spec["limit_mw"] <= ceiling, name
            assert spec["limit_mw"] % step == 0, name

    def test_every_capacity_fits(self, seed):
        top = _js_const("PMAX_MAX_MW")
        step = _js_const("PMAX_STEP_MW")
        for name, gen in seed["config"]["fleet"].items():
            assert gen["pmax_mw"] <= top, name
            assert gen["pmax_mw"] % step == 0, name

    def test_every_offer_fits(self, seed):
        top = _js_const("COST_MAX_USD")
        step = _js_const("COST_STEP_USD")
        for name, gen in seed["config"]["fleet"].items():
            assert gen["cost_usd_per_mwh"] <= top, name
            assert gen["cost_usd_per_mwh"] % step == 0, name

    def test_every_bid_peak_fits(self, seed):
        top = _js_const("PEAK_MAX_MW")
        step = _js_const("PEAK_STEP_MW")
        for name, bid in seed["config"]["load"]["bids"].items():
            assert bid["peak_mw"] <= top, name
            assert bid["peak_mw"] % step == 0, name

    def test_the_unlimited_notch_sits_one_step_past_the_ceiling(self):
        """It is a position, not a rating. One step past the end so no finite
        rating can land on it and be read as infinite.

        Asserted on the SOURCE rather than on a value, because the notch is
        derived from the other two constants in controls.js and pinning it to
        a number here would be a third place to keep in step.
        """
        source = CONTROLS_JS.read_text()
        assert "const LIMIT_INF_POS = LIMIT_CEILING_MW + LIMIT_STEP_MW;" in source

    def test_the_offer_slider_does_not_reach_the_cap(self, seed):
        """Deliberate. A generator offering at the system-wide offer cap would
        price every hour at scarcity, which is a scenario to write in a config
        rather than one to reach by dragging past everything interesting."""
        assert _js_const("COST_MAX_USD") < seed["market"]["offer_cap_usd_per_mwh"]


class TestTheLeverModuleIsServed:
    def test_controls_is_served_as_javascript(self, client):
        r = client.get("/js/controls.js")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]


# --------------------------------------------------------------------- W2.5
# The editing grammar: drag moves a bus, every other structural edit is an
# armed mode. Add or remove a bus, connect or cut a line, add or remove a
# generator.
#
# THE INTERACTION IS NOT TESTED HERE AND CANNOT BE. There is no JavaScript
# runtime in this environment and adding one would be a build step, which web/
# exists without. So the grammar itself -- arming, hit-testing, the pending
# first bus of a connect, the keyboard path, undo -- is driven in a real
# browser by web/check-grammar.html, which iframes the app, dispatches
# synthetic events on the real marks and reads the result back out of the
# page's own "what is posted" panel.
#
# What is asserted here is the OTHER HALF: that each edit the grammar can
# produce is a scenario this engine prices, and that the two refusals the
# editor must avoid are real rather than imagined. Those are claims about the
# engine, they are what would make an edit fail in front of a visitor, and
# pytest is where they belong.

EDITS_JS = Path("web/js/edits.js")
STATE_JS = Path("web/js/state.js")


def _js_const_in(path, name):
    """A numeric `export const NAME = 123;` out of a module in web/js/."""
    m = re.search(rf"^(?:export )?const {name} = (-?[\d.]+);", path.read_text(), re.M)
    assert m, f"{name} is not a plain numeric const in {path}"
    return float(m.group(1))


@pytest.fixture(scope="module")
def defaults():
    """The defaults policy, read from the module that declares it.

    A DEFAULT IS A MARKET ASSUMPTION, NOT A UI DETAIL (state.js says so at
    length), so the tests below price the editor's actual numbers rather than
    numbers that happen to agree with them today.
    """
    return {
        "reactance_pu": _js_const_in(STATE_JS, "DEFAULT_REACTANCE_PU"),
        "cost_usd_per_mwh": _js_const_in(STATE_JS, "DEFAULT_GEN_COST_USD_PER_MWH"),
        "pmax_mw": _js_const_in(STATE_JS, "DEFAULT_GEN_PMAX_MW"),
    }


def _edited(seed, mutate):
    """The seed config with one structural edit applied, as the editor would."""
    config = json.loads(json.dumps(seed["config"]))
    mutate(config)
    return config


def _clear(client, config, slack, limits=None, expect=200):
    r = client.post("/clear", json={"config": config, "slack": slack, "limits": limits})
    assert r.status_code == expect, r.text
    return r.json()


def _settles(cleared):
    """The claim the whole repo rests on, per island AND per hour.

    Never summed in either dimension: a positive residual in one island or one
    hour would cancel a negative one in another, which is the mistake CLAUDE.md
    names twice.
    """
    return all(
        abs(residual) < 1e-6
        for ledger in cleared["settlement"].values()
        for residual in ledger["residual"]
    )


class TestTheEditsThatChangeTheNetwork:
    def test_a_new_bus_on_a_new_line_gets_a_real_lmp(self, client, seed, defaults):
        """Add bus, then connect: the two edits a visitor makes in that order.

        A connected bus with no generator and no bid prices correctly and gets
        a real LMP -- CLAUDE.md lists that under "not a bug, do not fix", and
        it is the whole reason the defaults policy adds nothing to a new bus.
        """
        config = _edited(seed, lambda c: (
            c["network"]["buses"].append("F"),
            c["network"]["branches"].update(
                {"AF": {"from": "A", "to": "F",
                        "reactance_pu": defaults["reactance_pu"], "limit_mw": "inf"}}
            ),
        ))
        out = _clear(client, config, seed["slack"])
        assert "F" in out["lmp"]
        assert len(out["lmp"]["F"]) == len(out["hours"])
        assert _settles(out)

    def test_a_new_line_is_unrated_and_therefore_never_binds(self, client, seed, defaults):
        """The editor gives a new line no rating, because one it invented would
        manufacture congestion nobody asked for. Stated as a price: mu is zero
        on it in every hour."""
        config = _edited(seed, lambda c: c["network"]["branches"].update(
            {"AC": {"from": "A", "to": "C",
                    "reactance_pu": defaults["reactance_pu"], "limit_mw": "inf"}}
        ))
        out = _clear(client, config, seed["slack"])
        assert all(m == 0.0 for m in out["mu"]["AC"])
        assert _settles(out)

    def test_a_second_line_between_the_same_pair_solves(self, client, seed, defaults):
        """Parallel branches are physical and are not a collision, which is why
        nextBranchName suffixes rather than refusing. The map bows them apart;
        the engine simply prices them."""
        config = _edited(seed, lambda c: c["network"]["branches"].update(
            {"AB2": {"from": "A", "to": "B",
                     "reactance_pu": defaults["reactance_pu"], "limit_mw": "inf"}}
        ))
        out = _clear(client, config, seed["slack"])
        assert {"AB", "AB2"} <= set(out["lines"])
        assert _settles(out)

    def test_cutting_lines_until_the_network_splits_prices_both_islands(self, client, seed):
        """Cut is the edit most likely to be a visitor's first act, and W1's
        answer is two markets rather than an error: one energy balance, one
        lambda, one slack and one settlement identity per island."""
        config = _edited(seed, lambda c: [
            c["network"]["branches"].pop(line) for line in ("AB", "AD", "AE")
        ])
        out = _clear(client, config, seed["slack"])
        assert len(out["islands"]) == 2
        assert set(out["lmbda"]) == set(out["islands"])
        # A is alone, and the island it is in is named by its own slack.
        assert ["A"] in [sorted(buses) for buses in out["islands"].values()]
        assert _settles(out)

    def test_removing_a_bus_must_take_its_branches_with_it(self, client, seed):
        """WHY removeBus is transitive, stated as the refusal it avoids.

        A branch naming a bus that is gone is not ignored -- the engine refuses
        the scenario by name. A removal that swept only the bus would put that
        sentence in front of a visitor, about an object they did not touch.
        """
        config = _edited(seed, lambda c: c["network"]["buses"].remove("E"))
        r = client.post("/clear", json={"config": config, "slack": seed["slack"]})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_scenario"
        assert "E" in r.json()["detail"]

    def test_a_rating_override_for_a_line_that_is_gone_is_refused(self, client, seed):
        """WHY cut() drops the limits override with the branch.

        clear() refuses an unknown limit key rather than ignoring it. Leaving
        the override behind would make the NEXT solve fail, naming a line the
        visitor had already removed -- a refusal one edit downstream of its
        cause, which is the worst kind to debug from a screen.
        """
        config = _edited(seed, lambda c: c["network"]["branches"].pop("DE"))
        r = client.post(
            "/clear",
            json={"config": config, "slack": seed["slack"], "limits": {"DE": 240.0}},
        )
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_scenario"
        assert "DE" in r.json()["detail"]


class TestTheEditsThatChangeTheFleet:
    def test_a_generator_at_the_editors_defaults_actually_runs(self, client, seed, defaults):
        """The defaults policy puts a new unit between the cheapest and dearest
        seeded offers, so adding one is neither always in merit nor never in
        it. Either extreme would make the lever look like it did nothing."""
        config = _edited(seed, lambda c: c["fleet"].update(
            {"g1": {"bus": "B", **{k: defaults[k] for k in ("cost_usd_per_mwh", "pmax_mw")}}}
        ))
        base = _clear(client, seed["config"], seed["slack"])
        out = _clear(client, config, seed["slack"])
        assert any(p > 0.0 for p in out["dispatch"]["g1"])
        assert out["lmp"] != base["lmp"]
        assert _settles(out)

    def test_removing_a_unit_reprices_rather_than_refusing(self, client, seed):
        base = _clear(client, seed["config"], seed["slack"])
        config = _edited(seed, lambda c: c["fleet"].pop("E1"))
        out = _clear(client, config, seed["slack"])
        assert "E1" not in out["dispatch"]
        assert out["lmp"] != base["lmp"]
        assert _settles(out)

    def test_removing_every_unit_sheds_at_the_cap_rather_than_refusing(self, client, seed):
        """Remove is armed and clicked, so removing all five is four clicks
        away. The editor emits only priced blocks, so an empty fleet is
        scarcity at the cap -- a price, not an error (W1)."""
        config = _edited(seed, lambda c: c["fleet"].clear())
        r = client.post("/clear", json={"config": config, "slack": seed["slack"]})
        if r.status_code == 200:
            out = r.json()
            cap = seed["market"]["offer_cap_usd_per_mwh"]
            assert all(q == 0.0 for q in out["bid_mw"]["D_firm"])
            assert all(p == pytest.approx(cap) for p in out["lmp"]["D"])
        else:
            # An empty fleet is a statement about the scenario, not about
            # whether the market clears, so a named refusal is also correct.
            assert r.json()["error"] == "invalid_scenario"


class TestRemovingTheSlackBus:
    """CLAUDE.md, W2.6: deleting the slack bus MOVES THE DROPDOWN, it does not
    422. Half of that lands here, in removeBus, because the alternative is a
    422 on the most ordinary edit on the page.

    The engine's refusal of a slack that is not a bus stays correct and stays
    in place -- it is the check that catches the editor failing to keep its own
    state in step. So the editor keeps it in step, and it uses the SAME RULE
    the engine's own fallback uses, so the two cannot disagree about where the
    slack went.
    """

    def test_the_engines_fallback_is_the_first_bus_in_config_order(self, client, seed):
        """The rule removeBus follows, read off the engine rather than assumed.

        This is the fallback for a caller with no dropdown -- a sweep, a
        notebook, a hand-edited config. The editor never reaches it, because it
        posts an explicit slack; it copies it so that if it ever did, the
        answer would be the same one.
        """
        config = _edited(seed, lambda c: (
            c["network"]["buses"].remove("D"),
            c["network"]["branches"].pop("AD"),
            c["network"]["branches"].pop("CD"),
            c["network"]["branches"].pop("DE"),
            c["fleet"].pop("D1"),
            c["load"]["bids"].pop("D_firm"),
        ))
        # slack=None: the config still RECORDS D, which is now gone.
        out = _clear(client, config, None)
        assert out["slack"] == config["network"]["buses"][0]

    def test_the_editors_explicit_slack_agrees_with_that_fallback(self, client, seed):
        """What the editor actually posts after removing the slack bus, and it
        must price identically to the fallback above -- same slack, same
        prices. A disagreement here would be the editor silently pricing a
        different market from the one a config-only caller gets."""
        config = _edited(seed, lambda c: (
            c["network"]["buses"].remove("D"),
            c["network"]["branches"].pop("AD"),
            c["network"]["branches"].pop("CD"),
            c["network"]["branches"].pop("DE"),
            c["fleet"].pop("D1"),
            c["load"]["bids"].pop("D_firm"),
        ))
        chosen = _clear(client, config, None)
        explicit = _clear(client, config, config["network"]["buses"][0])
        assert explicit["slack"] == chosen["slack"]
        assert explicit["lmp"] == chosen["lmp"]
        assert explicit["lmbda"] == chosen["lmbda"]

    def test_a_slack_that_is_not_a_bus_is_still_refused(self, client, seed):
        """The check that catches the editor failing. Kept, deliberately: a
        typo that silently answered about a different bus is how a sweep
        reports a day of the wrong lambda and nobody notices."""
        config = _edited(seed, lambda c: c["network"]["buses"].remove("E"))
        r = client.post("/clear", json={"config": seed["config"], "slack": "E2"})
        assert r.status_code == 422
        assert r.json()["error"] == "invalid_scenario"
        assert "E2" in r.json()["detail"]


class TestTheGrammarModulesAreServed:
    """An ES module served as text/plain is refused by the browser with a MIME
    error and no other symptom, so every module the page imports is asserted
    rather than assumed."""

    @pytest.mark.parametrize("module", ["edits.js", "grammar.js"])
    def test_the_module_is_served_as_javascript(self, client, module):
        r = client.get(f"/js/{module}")
        assert r.status_code == 200
        assert "javascript" in r.headers["content-type"]

    def test_the_browser_harness_is_served_but_not_linked(self, client):
        """web/check-grammar.html drives the grammar in a real browser, which
        is the only runtime this repo has for JavaScript. It is a development
        page: served, because it has to be same-origin with the app to iframe
        it, and deliberately not reachable from the app."""
        assert client.get("/check-grammar.html").status_code == 200
        assert "check-grammar" not in client.get("/").text


# --------------------------------------------------------------------- W2.8
# The acceptance test for the slack lever, and it is the one assertion in W2
# that could pass on a build where the lever does nothing at all.
#
# What must hold, from CLAUDE.md trap 2:
#
#     lambda moves.               lambda IS the LMP at the slack.
#     the congestion split moves. PTDF[l, slack] = 0 by construction.
#     no LMP moves.               the two changes cancel exactly.
#     no bill moves.              a slack bug is INVISIBLE in settlement.
#
# The last line is why this test exists at all: every payment, revenue and
# rent is right whichever slack is wrong, so a slack bug shows only if lambda
# and the congestion component are asserted separately from the price.
#
# Two things the assertion needs and does not get for free.
#
# 1. pytest.approx, not equality. A different slack is a different PTDF, so it
#    is a different LP; HiGHS factorizes different bases and the primal itself
#    moves a few ulps. Measured here on the seed, worst over 24 hours and all
#    five slacks: LMP 2.1e-13, payments 1.1e-10, dispatch 6.3e-12 -- the same
#    figures CLAUDE.md's trap 2 table carries, since this is the same case5.
#    abs=1e-9 clears the debris by three orders and would still catch a price
#    that actually moved.
#
# 2. A unique optimum, asserted before it is relied on. What is slack-
#    invariant is the SET of optimal prices; which member of it the solver
#    hands back is not guaranteed, and under degeneracy a different PTDF can
#    pivot to a different vertex. On a degenerate fixture this test would
#    flake, correctly -- trap 3 against trap 2. So uniqueness is a precondition
#    with its own tests rather than a remark.
#
#    That flake is still unobserved, and W2.9 measured why. No setting of
#    w1.yaml's limits reaches a degenerate AND congested optimum -- swept over
#    1201 DE ratings and all 24 hours, the only pattern is basic 0 against 1
#    row, which is uncongested, and trap 2 says lambda does not move with the
#    slack there. See tests/test_w2_degenerate_optimum.py, which asserts the
#    five slacks agreeing at that breakpoint.

SLACK_TOL = 1e-9        # far above the measured 1.1e-10 debris
LAMBDA_MOVE = 1.0       # far below the smallest real move, $9.94 at slack C


def _at_bound(cleared, gen, hour):
    return cleared["gen_status"][gen][hour] != "interior"


class TestTheFixturesOptimumIsUnique:
    """The precondition, measured on the seed rather than assumed of it.

    Both halves are read off fields clear() already returns, which is the
    reason they can be asserted at all: "gen_status" says where a unit sits
    and "reduced_cost" says what one more MW is worth to it.

      primal unique       every variable at a bound has a strictly non-zero
                          reduced cost. A zero there is a second optimal
                          dispatch at the same cost, reachable by moving that
                          unit off its bound for free.

      dual unique         per island and hour, the number of units strictly
                          between their bounds equals 1 + the number of
                          binding lines -- one basic variable per active row,
                          the energy balance plus each binding limit. Fewer
                          means a basic variable sitting exactly on a bound,
                          which is primal degeneracy, which is multiple
                          optimal duals, which is multiple prices.

    Measured on the seed: the slimmest reduced cost at a bound is $0.057/MWh,
    at hours 07-21. Small, and strictly non-zero, which is the whole claim.
    """

    @pytest.fixture(scope="class")
    def cleared(self, client, seed):
        return _clear(client, seed["config"], seed["slack"])

    def test_no_unit_sits_on_a_bound_for_free(self, cleared):
        for gen in cleared["generators"]:
            for t in cleared["hours"]:
                if _at_bound(cleared, gen, t):
                    assert abs(cleared["reduced_cost"][gen][t]) > 1e-6, (gen, t)

    def test_no_bid_is_partly_served(self, cleared):
        # A bid strictly between 0 and its quantity is a basic variable too,
        # and would have to be counted in the balance below. Every firm bid is
        # valued at the cap, so none is.
        for bid in cleared["bids"]:
            for t in cleared["hours"]:
                asked = cleared["bid_mw"][bid][t]
                assert cleared["served"][bid][t] == pytest.approx(asked)

    def test_one_basic_unit_per_active_row(self, cleared):
        for island, buses in cleared["islands"].items():
            gens = [g for g, bus in cleared["gen_bus"].items() if bus in buses]
            lines = cleared["island_lines"][island]
            for t in cleared["hours"]:
                interior = sum(1 for g in gens if not _at_bound(cleared, g, t))
                binding = sum(1 for l in lines if abs(cleared["mu"][l][t]) > 1e-9)
                assert interior == 1 + binding, (island, t, interior, binding)


class TestMovingTheSlackMovesLambdaAndNoPrice:
    """The lever, posted the way the editor posts it: the seed's config, an
    explicit slack, null limits. Every bus in turn, so the assertion is not
    resting on one lucky pair."""

    @pytest.fixture(scope="class")
    def solved(self, client, seed):
        return {bus: _clear(client, seed["config"], bus)
                for bus in seed["config"]["network"]["buses"]}

    @pytest.fixture(scope="class")
    def base(self, solved, seed):
        return solved[seed["slack"]]

    @pytest.fixture(scope="class")
    def congested(self, base):
        """The hours with a binding line, which are the only ones where the
        slack has anything to rearrange.

        With nothing congested every mu is zero, so every LMP is the same
        number and lambda is that number under whichever slack -- the split is
        lambda plus nothing, and moving the origin of a zero moves nothing.
        Congestion is what gives lambda somewhere to move to. The seed
        congests at hours 07-22 and does not at 00-06 or 23, and both halves
        are asserted below rather than one being skipped.
        """
        hours = [t for t in base["hours"]
                 if any(abs(base["mu"][l][t]) > 1e-9 for l in base["lines"])]
        assert hours, "the fixture has no congested hour, and the lever has nothing to move"
        return hours

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_lambda_moves_where_a_line_binds(self, solved, base, seed, congested, bus):
        """The half that fails on a build where the lever does nothing.

        Asserted as a margin, not as inequality: two floats a ulp apart are
        unequal and would satisfy a weaker test while the page showed no
        change a reader could see. The smallest real move on this fixture is
        $9.94, at slack C.
        """
        moved = solved[bus]
        for t in congested:
            assert abs(moved["lmbda"][bus][t] - base["lmbda"][seed["slack"]][t]) > LAMBDA_MOVE

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_lambda_does_not_move_where_nothing_binds(self, solved, base, seed, congested, bus):
        """And the other half, which is not a weaker version of it.

        An uncongested hour has one price everywhere, so lambda is that price
        whatever the slack. A lambda that moved here would mean the slack had
        reached something other than the accounting origin.
        """
        moved = solved[bus]
        for t in set(moved["hours"]) - set(congested):
            assert moved["lmbda"][bus][t] == pytest.approx(
                base["lmbda"][seed["slack"]][t], abs=SLACK_TOL
            ), t

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_the_congestion_split_moves_with_it(self, solved, base, congested, bus):
        """The other side of the cancellation, and the reason no LMP moves.

        In a congested hour, moving the slack must move some bus's congestion
        component by the margin lambda moved, in the other direction.
        """
        moved = solved[bus]
        for t in congested:
            assert max(abs(moved["congestion"][b][t] - base["congestion"][b][t])
                       for b in moved["buses"]) > LAMBDA_MOVE

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_no_lmp_moves(self, solved, base, bus):
        moved = solved[bus]
        for b in moved["buses"]:
            for t in moved["hours"]:
                assert moved["lmp"][b][t] == pytest.approx(
                    base["lmp"][b][t], abs=SLACK_TOL
                ), (b, t)

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_the_split_still_adds_up_to_the_price(self, solved, bus):
        """lmp == lmbda + congestion, under whichever slack.

        Not arithmetic the browser is doing -- all three are fields of the
        return. This asserts they are consistent so a view may print any two
        of them beside the third.
        """
        moved = solved[bus]
        for b in moved["buses"]:
            island = moved["island_of"][b]
            for t in moved["hours"]:
                assert moved["lmp"][b][t] == pytest.approx(
                    moved["lmbda"][island][t] + moved["congestion"][b][t]
                )

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    @pytest.mark.parametrize("field", ["payments", "revenue", "congestion_rent",
                                       "rent_from_duals"])
    def test_no_settlement_figure_moves(self, solved, base, seed, bus, field):
        moved = solved[bus]["settlement"][bus]
        home = base["settlement"][seed["slack"]]
        for t in solved[bus]["hours"]:
            assert moved[field][t] == pytest.approx(home[field][t], abs=SLACK_TOL), t

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_the_identity_holds_under_every_slack(self, solved, bus):
        assert _settles(solved[bus])

    @pytest.mark.parametrize("bus", ["A", "B", "C", "E"])
    def test_no_dispatch_and_no_flow_moves(self, solved, base, bus):
        """The primal, which trap 2 says moves a few ulps and nothing more.

        Worth asserting separately from the prices: a slack that reached the
        physics would change what the generators actually did, and that is a
        different and much worse bug than a mispriced one.
        """
        moved = solved[bus]
        for gen in moved["generators"]:
            for t in moved["hours"]:
                assert moved["dispatch"][gen][t] == pytest.approx(
                    base["dispatch"][gen][t], abs=SLACK_TOL
                ), (gen, t)
        for line in moved["lines"]:
            for t in moved["hours"]:
                assert moved["flows"][line][t] == pytest.approx(
                    base["flows"][line][t], abs=SLACK_TOL
                ), (line, t)


class TestDeletingTheSlackIsNotAnErrorAndDeletingAnythingElseIsNotAMove:
    """W2.6's promise, stated as acceptance rather than as mechanism.

    TestRemovingTheSlackBus above asserts WHERE the slack goes. This asserts
    the two things a visitor would notice: the edit is priced rather than
    refused, and an unrelated deletion does not move the slack at all. A slack
    that wandered on an unrelated edit would make lambda jump on screen for no
    reason a reader could see.
    """

    def _without_d(self, seed):
        return _edited(seed, lambda c: (
            c["network"]["buses"].remove("D"),
            c["network"]["branches"].pop("AD"),
            c["network"]["branches"].pop("CD"),
            c["network"]["branches"].pop("DE"),
            c["fleet"].pop("D1"),
            c["load"]["bids"].pop("D_firm"),
        ))

    def test_deleting_the_slack_bus_is_priced(self, client, seed):
        config = self._without_d(seed)
        # What the editor posts after removeBus: its own new slack, which it
        # keeps in step with its bus list rather than leaving stale.
        out = _clear(client, config, config["network"]["buses"][0])
        assert out["slack"] == "A"
        assert _settles(out)

    def test_deleting_an_unrelated_bus_does_not_move_the_slack(self, client, seed):
        config = _edited(seed, lambda c: (
            c["network"]["buses"].remove("E"),
            c["network"]["branches"].pop("AE"),
            c["network"]["branches"].pop("DE"),
            c["fleet"].pop("E1"),
        ))
        out = _clear(client, config, seed["slack"])
        assert out["slack"] == seed["slack"] == "D"
        assert list(out["islands"]) == ["D"]


class TestTheEmitterRoundTripIsCheckedInABrowser:
    """toConfig() is JavaScript and there is no JavaScript runtime here, so
    the emitter's round trip runs in web/check-emit.html. What pytest owns is
    the other half of the chain: the seed the emitter reads is w1.yaml, which
    TestTheSeedIsW1AndNotACopyThatDrifted asserts field for field."""

    def test_the_emitter_harness_is_served_but_not_linked(self, client):
        assert client.get("/check-emit.html").status_code == 200
        assert "check-emit" not in client.get("/").text

    def test_the_harness_imports_the_module_the_page_imports(self, client):
        # A harness holding its own copy of toConfig would pass forever while
        # the editor emitted something else.
        assert './js/state.js"' in Path("web/check-emit.html").read_text()
        assert client.get("/js/state.js").status_code == 200
