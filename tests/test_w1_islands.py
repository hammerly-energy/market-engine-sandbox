r"""W1: a cut network is two markets, not an error.

The second of W1's three formulation questions. What does an island mean?

    REFUSE                          PRICE EACH ISLAND
    ------                          -----------------
    ptdf.py raised, naming the      one balance row per component, one
    stranded buses. Clean, and      lambda per component, one settlement
    wrong the moment a visitor's    identity per component. What a real
    first act is to cut a line.     ISO does.

The formulation insight, and the reason this is a forty-line change rather
than a rewrite: an island is a BALANCE CONSTRAINT, not a PTDF. One
system-wide balance row says total generation equals total demand, which
lets a generator in one island serve load in another through a line that is
not there -- and no flow limit stops it, because the constraint set only
contains lines that exist. The PTDF failure was a symptom.

So the PTDF goes block diagonal (an injection in one island moves no line in
another, which is physics, not bookkeeping), m.inj and m.f and both flow
limits are untouched, and only the balance is re-indexed.

Islands are named by their SLACK, because lambda IS the LMP at the slack.
An index would mean nothing to a reader and would renumber the moment
another line is cut.

Grouped by lifespan. TestConnectedIsUnchanged is the control and must hold
forever: a network in one piece has to clear exactly as it did before any of
this existed.
"""

import json
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from src.api.app import app
from src.ingest.scenario import build_scenario, load_config, scenario_from_config
from src.model.clearing import clear
from src.network.ptdf import island_slacks, ptdf, ptdf_blocks

M4_CONFIG = "configs/m4.yaml"
W1_CONFIG = "configs/w1.yaml"
PEAK_HOUR = 18

PUBLISHED_LMP = {"A": 16.9774, "B": 26.3845, "C": 30.0000, "D": 39.9427, "E": 10.0000}

# Cutting these three splits case5 into {A, E} and {B, C, D}. Chosen so that
# BOTH halves are interesting: one has 810 MW of capacity and no load at all,
# the other has 720 MW against 1000 MW of peak demand and must shed.
CUT = ("AB", "AD", "DE")


def cut_config(path=W1_CONFIG, lines=CUT, **fleet):
    config = load_config(path)
    for line in lines:
        del config["network"]["branches"][line]
    for spec in config["fleet"].values():
        spec.update(fleet)
    return config


# ----------------------------------------------------------- the control


class TestConnectedIsUnchanged:
    """One piece clears exactly as it did. Forever."""

    def test_the_block_diagonal_ptdf_is_the_plain_one(self):
        scenario = build_scenario(M4_CONFIG)
        buses = [b.name for b in scenario.buses]
        branches = list(scenario.branches)
        plain = ptdf(buses, branches, "D")
        blocks, islands = ptdf_blocks(buses, branches, "D")
        assert np.allclose(plain, blocks)
        assert islands == {"D": buses}

    def test_the_published_lmps_survive(self):
        cleared = clear(build_scenario(M4_CONFIG))
        for bus, expected in PUBLISHED_LMP.items():
            assert cleared["lmp"][bus, PEAK_HOUR] == pytest.approx(expected, abs=1e-4)
        assert cleared["lmbda"]["D", PEAK_HOUR] == pytest.approx(39.9427, abs=1e-4)

    def test_one_island_named_by_the_slack(self):
        cleared = clear(build_scenario(M4_CONFIG))
        assert list(cleared["islands"]) == ["D"]
        assert set(cleared["island_of"].values()) == {"D"}

    def test_ptdf_still_refuses_a_disconnected_network(self):
        """ptdf() is the single-component primitive and stays one.

        A PTDF relative to ONE slack is a single-component object. ptdf_blocks
        is the thing that knows there can be several, and it is built by
        calling ptdf() per component -- so there is no second implementation
        of the linear algebra and no new place for a sign to be wrong.
        """
        scenario = scenario_from_config(cut_config(), origin="<test>")
        buses = [b.name for b in scenario.buses]
        with pytest.raises(ValueError, match="disconnected"):
            ptdf(buses, list(scenario.branches), "D")


# ----------------------------------------------------------- the slack rule


class TestIslandSlacks:
    """Where the extra slacks come from, which is a decision, not a detail."""

    def _net(self, lines=CUT):
        scenario = scenario_from_config(cut_config(lines=lines), origin="<test>")
        return [b.name for b in scenario.buses], list(scenario.branches)

    def test_the_users_slack_keeps_its_island(self):
        """Cutting a line must not move the slack the UI is displaying."""
        buses, branches = self._net()
        assert island_slacks(buses, branches, "D") == {"A": ["A", "E"],
                                                       "D": ["B", "C", "D"]}

    def test_every_other_island_takes_its_first_bus(self):
        buses, branches = self._net()
        # With the slack at B, its island is keyed B and the other still takes
        # A -- the first of its buses in the caller's order.
        assert island_slacks(buses, branches, "B") == {"A": ["A", "E"],
                                                       "B": ["B", "C", "D"]}

    def test_a_lone_bus_is_an_island(self):
        """E alone, with no line at all. It still gets a slack and a market."""
        buses, branches = self._net(lines=("AE", "DE"))
        assert island_slacks(buses, branches, "D") == {"D": ["A", "B", "C", "D"],
                                                       "E": ["E"]}

    def test_the_ptdf_is_block_diagonal(self):
        """An injection in one island moves no line in another. Physics."""
        buses, branches = self._net()
        P, islands = ptdf_blocks(buses, branches, "D")
        col = {b: j for j, b in enumerate(buses)}
        row = {br.name: k for k, br in enumerate(branches)}
        # AE lives in island A; its row must be zero in every column of the
        # other island.
        for bus in ("B", "C", "D"):
            assert P[row["AE"], col[bus]] == 0.0
        for bus in ("A", "E"):
            assert P[row["BC"], col[bus]] == 0.0


# --------------------------------------------------------- two markets


class TestTwoMarkets:
    """The goal: a cut network prices, and the two halves are independent."""

    @pytest.fixture(scope="class")
    def split(self):
        return clear(scenario_from_config(cut_config(), origin="<test>"))

    def test_it_clears_instead_of_raising(self, split):
        assert list(split["islands"]) == ["A", "D"]
        assert split["islands"]["A"] == ["A", "E"]
        assert split["islands"]["D"] == ["B", "C", "D"]

    def test_two_different_lambdas_in_one_hour(self, split):
        """The whole point. One number per market, not one per system."""
        assert split["lmbda"]["D", PEAK_HOUR] == pytest.approx(5000.0)
        assert split["lmbda"]["A", PEAK_HOUR] != pytest.approx(5000.0)

    def test_the_short_island_sheds_and_prices_at_the_cap(self, split):
        """{B, C, D} has 720 MW against 1000 MW of demand.

        It cannot import: the lines out of it were cut. So it serves what it
        can and prices at the valuation of the first MW it declined -- which
        is a scarcity price, and is only reachable because W1's demand side
        landed first. Before that this island was infeasible and took the
        whole solve down with it.
        """
        served = sum(split["served"][k, PEAK_HOUR] for k in split["bid_value"])
        asked = sum(split["bid_mw"][k, PEAK_HOUR] for k in split["bid_value"])
        assert 0 < served < asked
        for bus in ("B", "C", "D"):
            assert split["lmp"][bus, PEAK_HOUR] == pytest.approx(5000.0)

    def test_the_stranded_island_cannot_help(self, split):
        """{A, E} holds 810 MW of capacity and is not allowed to sell it.

        This is the assertion the whole re-indexing exists for. With ONE
        balance row, Brighton at E would have served load at bus B through a
        line that is not there, and nothing in the flow limits would have
        objected.
        """
        for gen in ("alta", "park_city", "brighton"):
            assert split["dispatch"][gen, PEAK_HOUR] == pytest.approx(0.0, abs=1e-6)

    def test_the_settlement_identity_holds_per_island_per_hour(self, split):
        """Never summed across islands. Summing them would let a positive
        residual in one cancel a negative one in the other -- the per-hour
        mistake, one dimension over."""
        for home in split["islands"]:
            for t in split["hours"]:
                assert split["settlement"][home, t]["residual"] == pytest.approx(
                    0.0, abs=1e-6
                )

    def test_an_island_with_generation_and_no_load_is_degenerate(self, split):
        """{A, E} serves nothing, so its lambda is not pinned by anything.

        Recorded rather than asserted to a value: with p = 0 and d = 0 the
        price is anywhere between zero and the cheapest offer, and which end
        HiGHS reports is a vertex choice. Trap 3. A view must say so rather
        than print the number as though it meant something.
        """
        lam = split["lmbda"]["A", PEAK_HOUR]
        assert -1e-6 <= lam <= 10.0 + 1e-6


# ------------------------------------------------------------- the wire


class TestIslandsOverHttp:
    """Two markets survive JSON, and the shape does not change with topology."""

    @pytest.fixture(scope="class")
    def client(self):
        return TestClient(app)

    def _post(self, client, config):
        # YAML's .inf has no JSON literal; bounds.py takes null for it.
        def as_wire(x):
            if isinstance(x, dict):
                return {k: as_wire(v) for k, v in x.items()}
            if isinstance(x, list):
                return [as_wire(v) for v in x]
            if isinstance(x, float) and math.isinf(x):
                return None
            return x

        r = client.post("/clear", json={"config": as_wire(config)})
        assert r.status_code == 200, r.text
        return r.json()

    def test_a_cut_network_is_a_200_not_a_4xx(self, client):
        """What CLAUDE.md's refusal table used to say was a clean ValueError.
        It was clean. It was also the wrong answer."""
        body = self._post(client, cut_config())
        assert set(body["islands"]) == {"A", "D"}
        t = body["hours"].index(PEAK_HOUR)
        assert body["lmbda"]["D"][t] == pytest.approx(5000.0)

    def test_lambda_is_always_keyed_by_island(self, client):
        """Never a bare array. A shape that changes with the topology is a
        shape the frontend branches on, and it would branch wrong the first
        time someone cut a line."""
        whole = self._post(client, load_config(W1_CONFIG))
        assert set(whole["lmbda"]) == {"D"}
        assert len(whole["lmbda"]["D"]) == len(whole["hours"])

    def test_the_residual_is_on_the_wire_for_every_island(self, client):
        body = self._post(client, cut_config())
        for home in body["islands"]:
            for r in body["settlement"][home]["residual"]:
                assert r == pytest.approx(0.0, abs=1e-6)
