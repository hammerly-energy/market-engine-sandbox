r"""W0 acceptance tests: the engine behind an HTTP boundary.

W0 adds exactly one new failure surface, and it is not the market -- the
formulation is M3's and M4's, untouched. What is new is that a stranger now
chooses the input, and the two ways that goes wrong are:

    THE WIRE LIES.   clear() keys by (name, hour) and JSON cannot. Any
                     re-shaping is a chance to align a series to the wrong
                     hour, drop a bus, or stringify an integer label -- and
                     every one of those returns a 200 with a plausible number
                     in it. So the test is not "the response parses". It is
                     that the HTTP body matches the IN-PROCESS clear() result
                     field for field, indexed back through "hours".

    THE BODY BITES.  A live HiGHS solve behind a public URL is a resource
                     vector. Every cap is asserted to REJECT BY NAME, and the
                     oversized cases are asserted to reject WITHOUT SOLVING --
                     a 413 that arrives after a solve has already cost the
                     thing the cap exists to prevent.

Grouped by lifespan. TestWireFidelity and TestRejects hold for as long as
there is an HTTP endpoint. TestProvisional holds only until W1 decides what a
market says when load cannot be served, and is written to fail loudly when
that changes rather than to be quietly correct afterwards.
"""

import json
import math

import pytest
from fastapi.testclient import TestClient

from src.api import bounds
from src.api.app import app
from src.ingest.scenario import load_config, scenario_from_config
from src.model.clearing import clear

M4_CONFIG = "configs/m4.yaml"
PEAK_HOUR = 18  # the hour where shape == 1.0, i.e. m3's published case

# The published PJM 5-bus LMPs, as tests/test_m3_network.py asserts them.
PUBLISHED_LMP = {"A": 16.9774, "B": 26.3845, "C": 30.0000, "D": 39.9427, "E": 10.0000}


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


def as_wire(config):
    """A config dict with YAML's .inf spelled the way JSON can carry it.

    float('inf') is not JSON. json.dumps emits the non-standard token
    Infinity for it, which is exactly the thing bounds.py accepts null and
    "inf" instead of -- so the test posts what a browser would post.
    """
    if isinstance(config, dict):
        return {k: as_wire(v) for k, v in config.items()}
    if isinstance(config, list):
        return [as_wire(v) for v in config]
    if isinstance(config, float) and math.isinf(config):
        return None
    return config


@pytest.fixture(scope="module")
def m4_config():
    return as_wire(load_config(M4_CONFIG))


@pytest.fixture(scope="module")
def in_process():
    """The same solve, called directly. The answer the wire must reproduce."""
    return clear(scenario_from_config(load_config(M4_CONFIG), origin=M4_CONFIG))


@pytest.fixture(scope="module")
def over_http(client, m4_config):
    r = client.post("/clear", json={"config": m4_config})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------- the W0 goal


class TestWireFidelity:
    """The HTTP body carries the in-process result and nothing else."""

    def test_the_published_lmps_come_back_over_http(self, over_http):
        """The W0 goal, stated at the one hour with a published answer.

        This is test_m3_network.py's regression assertion, run through JSON.
        If the wire re-shaping is wrong this is the first thing to break,
        because it is the only hour whose right answer was published by
        someone other than this repo.
        """
        t = over_http["hours"].index(PEAK_HOUR)
        got = {b: over_http["lmp"][b][t] for b in over_http["buses"]}
        for bus, expected in PUBLISHED_LMP.items():
            assert got[bus] == pytest.approx(expected, abs=1e-4)

    @pytest.mark.parametrize(
        "field",
        ["dispatch", "flows", "mu", "lmp", "congestion", "headroom",
         "reduced_cost", "served", "bid_mw"],
    )
    def test_every_series_matches_the_in_process_result(
        self, over_http, in_process, field
    ):
        """Field for field, indexed back through "hours".

        Not a comparison of two encodings -- the right-hand side is the
        engine's own (name, hour) dict. That is what makes this an alignment
        test: a series rotated by one hour, or attached to the wrong bus,
        fails here and passes every "does it parse" check.
        """
        names = {
            "dispatch": over_http["generators"],
            "flows": over_http["lines"],
            "mu": over_http["lines"],
            "lmp": over_http["buses"],
            "congestion": over_http["buses"],
            "headroom": over_http["generators"],
            "reduced_cost": over_http["generators"],
            "served": over_http["bids"],
            "bid_mw": over_http["bids"],
        }[field]
        assert set(names) == {n for n, _ in in_process[field]}
        for n in names:
            series = over_http[field][n]
            assert len(series) == len(over_http["hours"])
            for t, hour in enumerate(over_http["hours"]):
                assert series[t] == pytest.approx(in_process[field][n, hour])

    def test_scalars_and_settlement_match(self, over_http, in_process):
        assert over_http["slack"] == in_process["slack"]
        assert over_http["buses"] == in_process["buses"]
        assert over_http["lines"] == in_process["lines"]
        assert over_http["cost"] == pytest.approx(in_process["cost"])
        for t, hour in enumerate(over_http["hours"]):
            assert over_http["lmbda"][t] == pytest.approx(in_process["lmbda"][hour])
            for f, series in over_http["settlement"].items():
                assert series[t] == pytest.approx(in_process["settlement"][hour][f])

    def test_the_residual_is_on_the_wire_and_is_zero_every_hour(self, over_http):
        """The claim the repo rests on, per hour, as the frontend receives it.

        Per hour and never summed: a day-level sum lets a positive residual in
        one hour cancel a negative one in another and report a clean zero over
        a broken solve.
        """
        for r in over_http["settlement"]["residual"]:
            assert r == pytest.approx(0.0, abs=1e-6)

    def test_hour_labels_keep_their_type(self, over_http):
        """0..23 arrive as integers, not as the strings a JSON key would force.

        This is the entire reason the series are arrays aligned to "hours"
        rather than objects keyed by hour. M3's hour label is the string
        "static" and M2's are ISO-8601 timestamps; a frontend that had to
        guess which of those a key was would guess wrong at some milestone.
        """
        assert over_http["hours"] == list(range(24))
        assert all(isinstance(h, int) for h in over_http["hours"])

    def test_an_unlimited_line_crosses_as_null(self, over_http):
        """JSON has no infinity. .inf goes out as null and comes back in as inf."""
        assert over_http["limits"]["DE"] == pytest.approx(240.0)
        assert over_http["limits"]["AD"] is None

    def test_the_body_is_standard_json(self, client, m4_config):
        """No NaN, no Infinity tokens -- both of which json.dumps emits happily
        and JSON.parse() rejects, so the failure would appear in a browser and
        not in Python."""
        text = client.post("/clear", json={"config": m4_config}).text
        assert "Infinity" not in text
        assert "NaN" not in text
        json.loads(text, parse_constant=lambda c: pytest.fail(f"non-standard {c}"))

    def test_the_fields_w3_needs_are_present(self, over_http, in_process):
        """congestion, gen_cost, gen_pmax and the marginal unit.

        Added at W0 on purpose. Three of W3's views cannot be drawn without
        them, and adding them mid-W3 would mean adding an engine field while
        a frontend is the thing being debugged.
        """
        t = over_http["hours"].index(PEAK_HOUR)
        assert over_http["gen_cost"]["brighton"] == pytest.approx(10.0)
        assert over_http["gen_pmax"]["solitude"] == pytest.approx(520.0)
        assert over_http["gen_bus"]["brighton"] == "E"
        # lmp = lambda + congestion, at every bus. Asserted so the frontend
        # never has to check it -- and never has to compute it.
        for b in over_http["buses"]:
            assert over_http["lmp"][b][t] == pytest.approx(
                over_http["lmbda"][t] + over_http["congestion"][b][t]
            )
        # The slack carries no congestion, by construction. Trap 2.
        assert over_http["congestion"][over_http["slack"]][t] == pytest.approx(0.0)
        # TWO units are interior at the peak hour, which is why status is
        # reported per generator rather than as one "marginal unit". DE binds,
        # so E is a separate pricing region: Brighton is interior at 466.5 of
        # 600 MW and sets LMP[E] = 10.00, its own offer, while Solitude is
        # interior at 323.5 of 520 MW and sets LMP[C] = 30.00.
        assert over_http["gen_status"]["brighton"][t] == "interior"
        assert over_http["gen_status"]["solitude"][t] == "interior"
        assert over_http["gen_status"]["park_city"][t] == "at_max"
        assert over_http["gen_status"]["sundance"][t] == "off"
        assert over_http["headroom"]["park_city"][t] == pytest.approx(0.0, abs=1e-6)

    def test_ptdf_is_shaped_lines_by_buses(self, over_http, in_process):
        P = over_http["PTDF"]
        assert len(P) == len(over_http["lines"])
        assert all(len(row) == len(over_http["buses"]) for row in P)
        for k, line in enumerate(over_http["lines"]):
            for j, bus in enumerate(over_http["buses"]):
                assert P[k][j] == pytest.approx(in_process["PTDF"][k][j])

    def test_the_levers_pass_through(self, client, m4_config, in_process):
        """slack and limits are clear()'s arguments, forwarded unchanged.

        The slack half is trap 2 in miniature and it is the acceptance test
        W2's dropdown will lean on: lambda moves and no LMP does.
        """
        moved = client.post(
            "/clear", json={"config": m4_config, "slack": "A"}
        ).json()
        t = moved["hours"].index(PEAK_HOUR)
        assert moved["lmbda"][t] != pytest.approx(in_process["lmbda"][PEAK_HOUR])
        for b in moved["buses"]:
            assert moved["lmp"][b][t] == pytest.approx(in_process["lmp"][b, PEAK_HOUR])

        relaxed = client.post(
            "/clear", json={"config": m4_config, "limits": {"DE": None}}
        ).json()
        assert relaxed["limits"]["DE"] is None
        # With the corridor out of E unlimited, nothing binds and one price
        # holds everywhere. That is the case5 story with its constraint off.
        assert relaxed["mu"]["DE"][t] == pytest.approx(0.0)
        assert len({round(relaxed["lmp"][b][t], 6) for b in relaxed["buses"]}) == 1


# --------------------------------------------------------- the hostile body


class TestRejects:
    """Every refusal is named, is a 4xx, and carries no traceback."""

    def assert_named(self, response, code, status=422):
        assert response.status_code == status, response.text
        body = response.json()
        assert body["error"] == code, body
        assert body["detail"] and "Traceback" not in body["detail"]
        return body

    def test_an_oversized_body_is_refused_without_solving(self, client, monkeypatch):
        """413 before the JSON is even parsed, let alone solved.

        The body here is not a valid config at all -- it is padding. If it
        were rejected for being malformed instead of for being large, the size
        cap would not be what is under test.
        """
        blob = json.dumps({"config": "x" * (bounds.MAX_BODY_BYTES + 100)})
        r = client.post(
            "/clear", content=blob, headers={"content-type": "application/json"}
        )
        self.assert_named(r, "body_too_large", status=413)

    def test_a_lying_content_length_does_not_get_through(self, client):
        """The declared length is a claim by the client; the stream is checked too."""
        blob = b'{"config": "' + b"x" * (bounds.MAX_BODY_BYTES + 100) + b'"}'
        r = client.post(
            "/clear",
            content=blob,
            headers={"content-type": "application/json", "content-length": "10"},
        )
        assert r.status_code == 413

    def test_malformed_json(self, client):
        r = client.post(
            "/clear", content=b"{not json", headers={"content-type": "application/json"}
        )
        self.assert_named(r, "malformed_json", status=400)

    def test_a_non_object_body(self, client):
        r = client.post("/clear", json=[1, 2, 3])
        self.assert_named(r, "malformed_json", status=400)

    @pytest.mark.parametrize(
        "mutate, code",
        [
            (lambda c: c["network"].__setitem__(
                "buses", [f"b{i}" for i in range(bounds.MAX_BUSES + 1)]),
             "too_many_buses"),
            (lambda c: c["network"].__setitem__(
                "branches", {f"l{i}": {"from": "A", "to": "B", "reactance_pu": 0.01,
                                       "limit_mw": 100.0}
                             for i in range(bounds.MAX_BRANCHES + 1)}),
             "too_many_branches"),
            (lambda c: c["fleet"].update(
                {f"g{i}": {"bus": "A", "cost_usd_per_mwh": 10.0, "pmax_mw": 10.0}
                 for i in range(bounds.MAX_GENERATORS + 1)}),
             "too_many_generators"),
            (lambda c: c["load"].__setitem__(
                "shape", [1.0] * (bounds.MAX_HOURS + 1)),
             "too_many_hours"),
        ],
    )
    def test_each_cap_rejects_by_name(self, client, m4_config, mutate, code):
        """Rejected, never truncated. A silently dropped bus would return a
        priced solve of a network the caller did not send."""
        config = json.loads(json.dumps(m4_config))
        mutate(config)
        self.assert_named(client.post("/clear", json={"config": config}), code)

    def test_a_live_data_source_is_not_reachable_over_http(self, client, m4_config):
        """load.source = eia930 would spend the server's API key, once per
        POST, on a stranger's say-so. It is refused before a Scenario exists."""
        config = json.loads(json.dumps(m4_config))
        config["load"] = {"source": "eia930", "respondent": "ERCO",
                          "local_date": "2024-08-19"}
        self.assert_named(client.post("/clear", json={"config": config}),
                          "unsupported_load_source")

    @pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
    def test_non_finite_numbers_are_refused(self, client, m4_config, token):
        """Python's json module parses these non-standard literals silently.

        A NaN cost does not raise anywhere downstream -- it solves, and every
        price comes back NaN. Same failure mode Branch.__post_init__ guards
        reactance against: a confident wrong answer.
        """
        blob = json.dumps({"config": m4_config}).replace('"limit_mw": 240.0',
                                                         f'"limit_mw": {token}')
        assert token in blob
        r = client.post("/clear", content=blob,
                        headers={"content-type": "application/json"})
        self.assert_named(r, "invalid_scenario")

    @pytest.mark.parametrize(
        "mutate, fragment",
        [
            # Cut both lines into E: the bus cannot reach the slack at all.
            (lambda c: [c["network"]["branches"].pop("AE"),
                        c["network"]["branches"].pop("DE")],
             "disconnected"),
            (lambda c: c["network"]["branches"]["AB"].__setitem__("reactance_pu", 0.0),
             "reactance_pu"),
            (lambda c: c["network"].__setitem__("buses", ["A", "A", "B", "C", "D", "E"]),
             "duplicate bus"),
            (lambda c: c["network"]["branches"]["AB"].__setitem__("to", "Z"),
             "not a declared bus"),
        ],
    )
    def test_what_the_engine_already_refuses_survives_the_wire(
        self, client, m4_config, mutate, fragment
    ):
        """The table in CLAUDE.md, asserted through HTTP.

        Those ValueError messages were written to be read by a person, so the
        endpoint passes them through verbatim instead of replacing them with
        something vaguer. This test is what stops a later refactor from
        flattening them into "invalid input".
        """
        config = json.loads(json.dumps(m4_config))
        mutate(config)
        body = self.assert_named(client.post("/clear", json={"config": config}),
                                 "invalid_scenario")
        assert fragment in body["detail"]

    def test_a_slack_that_is_not_a_bus(self, client, m4_config):
        body = self.assert_named(
            client.post("/clear", json={"config": m4_config, "slack": "Z"}),
            "invalid_scenario",
        )
        assert "slack 'Z' is not a bus" in body["detail"]

    def test_a_limit_override_for_an_unknown_line(self, client, m4_config):
        self.assert_named(
            client.post("/clear", json={"config": m4_config, "limits": {"ZZ": 100.0}}),
            "invalid_scenario",
        )

    def test_the_caps_are_published(self, client):
        """A client can refuse a body before it posts it."""
        published = client.get("/limits").json()
        assert published["max_buses"] == bounds.MAX_BUSES
        assert "eia930" not in published["load_sources"]


class TestGeneratorStatus:
    """Status and money must agree. An engine invariant, seen through the wire.

    This is the LP's own optimality condition restated in dollars, so it holds
    at every hour of every scenario, forever. It is asserted here rather than
    in an engine test file because W0 is when the fields were added -- and
    because a frontend colouring a merit-order stack by status while labelling
    it with reduced_cost needs the two to never contradict each other.
    """

    def test_status_and_reduced_cost_never_contradict(self, over_http):
        for g in over_http["generators"]:
            for t, hour in enumerate(over_http["hours"]):
                status = over_http["gen_status"][g][t]
                rc = over_http["reduced_cost"][g][t]
                if status == "interior":
                    # Indifferent: its offer IS the price at its bus. The
                    # honest version of "marginal".
                    assert rc == pytest.approx(0.0, abs=1e-6), (g, hour, rc)
                elif status == "at_max":
                    # Full because it wants to be. A negative reduced cost
                    # here would mean the LP is dispatching a unit at a loss.
                    assert rc >= -1e-6, (g, hour, rc)
                else:
                    # Off because the price does not cover its offer. A
                    # positive reduced cost here would mean money left on the
                    # table, i.e. a dual extraction bug.
                    assert rc <= 1e-6, (g, hour, rc)

    def test_headroom_is_capacity_minus_dispatch(self, over_http):
        for g in over_http["generators"]:
            for t in range(len(over_http["hours"])):
                assert over_http["headroom"][g][t] == pytest.approx(
                    over_http["gen_pmax"][g] - over_http["dispatch"][g][t]
                )

    def test_every_generator_and_hour_has_a_status(self, over_http):
        allowed = {"off", "interior", "at_max"}
        for g in over_http["generators"]:
            series = over_http["gen_status"][g]
            assert len(series) == len(over_http["hours"])
            assert set(series) <= allowed


# ------------------------------------------------------------- the demand side


class TestDemandSide:
    """A market that can decline to serve someone, seen over HTTP.

    W1 answered the question W0 could only name: what does the engine say
    when load cannot be served? It says the last MW was worth $5000 to
    somebody who did not get it. What this class checks is that the answer
    SURVIVES THE WIRE -- a 200 with a scarcity price on it, and the gap
    between what was asked for and what was served visible rather than
    implied.
    """

    @pytest.fixture(scope="class")
    def w1_config(self):
        return as_wire(load_config("configs/w1.yaml"))

    @pytest.fixture(scope="class")
    def short(self, client, w1_config):
        """case5's day with every unit capped at 50 MW. 250 of 1000 MW."""
        config = json.loads(json.dumps(w1_config))
        for spec in config["fleet"].values():
            spec["pmax_mw"] = 50.0
        r = client.post("/clear", json={"config": config})
        assert r.status_code == 200, r.text
        return r.json()

    def test_a_shortfall_is_a_priced_solve_not_an_error(self, short):
        """The W1 goal, over HTTP. No 4xx, no traceback -- a price."""
        t = short["hours"].index(PEAK_HOUR)
        assert short["lmbda"][t] == pytest.approx(5000.0)
        assert all(short["lmp"][b][t] == pytest.approx(5000.0) for b in short["buses"])

    def test_curtailment_is_visible_and_not_implied(self, short):
        """asked vs served, per bid. A view without this shows a market that
        always clears, which is exactly what W1 stopped being true."""
        t = short["hours"].index(PEAK_HOUR)
        asked = sum(short["bid_mw"][k][t] for k in short["bids"])
        served = sum(short["served"][k][t] for k in short["bids"])
        assert asked == pytest.approx(1000.0)
        assert 0 < served < asked

    def test_the_residual_is_still_zero_in_a_short_hour(self, short):
        """Billed on what load took, not what it asked for."""
        for r in short["settlement"]["residual"]:
            assert r == pytest.approx(0.0, abs=1e-6)

    def test_an_inelastic_bid_crosses_as_a_null_value(self, client, m4_config):
        """None is a claim -- must be served, no walk-away price -- and not a
        missing number. configs/m4.yaml's profile source is inelastic."""
        body = client.post("/clear", json={"config": m4_config}).json()
        assert set(body["bids"]) == {"B_load", "C_load", "D_load"}
        assert all(v is None for v in body["bid_value"].values())
        assert body["benefit"] == pytest.approx(0.0)

    def test_a_priced_bid_crosses_with_its_value(self, client, w1_config):
        body = client.post("/clear", json={"config": w1_config}).json()
        assert body["bid_value"] == {"B_firm": 5000.0, "C_firm": 5000.0,
                                     "D_firm": 5000.0}
        assert body["bid_bus"]["B_firm"] == "B"

    def test_the_blocks_source_matches_the_profile_source_over_http(
        self, client, w1_config, m4_config
    ):
        """configs/w1.yaml restates configs/m4.yaml. Bit-identical, on the
        wire as in process -- the control the demand side is measured against."""
        blocks = client.post("/clear", json={"config": w1_config}).json()
        profile = client.post("/clear", json={"config": m4_config}).json()
        for bus in profile["buses"]:
            assert blocks["lmp"][bus] == pytest.approx(profile["lmp"][bus])
        assert blocks["cost"] == pytest.approx(profile["cost"])


# -------------------------------------------------------------- provisional


class TestProvisional:
    """Holds only for INELASTIC demand, and W1 narrowed it to that.

    A scenario whose bids are priced can always decline to serve them, so it
    cannot be infeasible on capacity. A scenario using the profile or static
    source cannot -- its demand must be served -- and there the old
    RuntimeError still stands. What W0 owes is that it arrives as a named 4xx
    and never as a traceback.

    This goes away entirely if the editor is settled as emitting only blocks
    configs, which is a W2 decision and is not made yet.
    """

    def test_inelastic_demand_can_still_be_infeasible(self, client, m4_config):
        config = json.loads(json.dumps(m4_config))
        for spec in config["fleet"].values():
            spec["pmax_mw"] = 1.0
        r = client.post("/clear", json={"config": config})
        assert r.status_code == 422, r.text
        body = r.json()
        assert body["error"] == "solve_failed"
        assert "infeasible" in body["detail"]
        assert "Traceback" not in body["detail"]
