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
        balance row, E1 at E would have served load at bus B through a
        line that is not there, and nothing in the flow limits would have
        objected.
        """
        for gen in ("A1", "A2", "E1"):
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


# ------------------------------------------------------- the deleted slack


class TestDeletedSlack:
    """W1's third question: what happens when the slack bus is deleted.

    CHOSEN, not refused. The editor holds the slack in its own state, so
    deleting a bus leaves it naming one that is gone -- and refusing there
    would make deleting the slack the one edit that breaks the site. It would
    also refuse for no physical reason: the slack is an accounting origin
    (trap 2), any bus works, and no LMP, dispatch, flow or settlement figure
    depends on which one. Only the LEVEL of lambda moves, because lambda is
    the LMP at the slack.

    Silent in the sense that it does not raise. NOT silent in the sense of
    unreported -- the chosen slack comes back under "slack" and names its
    island in "islands" and "lmbda". That is the same rule island_slacks
    follows: a number the UI displays may not be picked privately.
    """

    def _without(self, *deleted):
        """case5 with buses deleted, and everything attached to them."""
        gone = set(deleted)
        config = load_config(W1_CONFIG)
        config["network"]["buses"] = [b for b in config["network"]["buses"]
                                      if b not in gone]
        config["network"]["branches"] = {
            n: spec for n, spec in config["network"]["branches"].items()
            if not gone & {spec["from"], spec["to"]}
        }
        config["fleet"] = {g: spec for g, spec in config["fleet"].items()
                           if spec["bus"] not in gone}
        config["load"]["bids"] = {k: spec for k, spec in config["load"]["bids"].items()
                                  if spec["bus"] not in gone}
        return scenario_from_config(config, origin="<test>")

    def test_deleting_the_slack_bus_still_clears(self):
        """configs/w1.yaml names D. Delete D and the market must still price."""
        cleared = clear(self._without("D"))
        assert "D" not in cleared["buses"]
        assert cleared["slack"] in cleared["buses"]

    def test_the_chosen_slack_is_reported(self):
        """The half that is not silent. A caller that asked for a bus which is
        gone can see which one it actually got."""
        cleared = clear(self._without("D"))
        assert cleared["slack"] == cleared["buses"][0]
        assert cleared["slack"] in cleared["islands"]
        assert (cleared["slack"], PEAK_HOUR) in cleared["lmbda"]

    def test_the_choice_is_reproducible(self):
        """First bus in the caller's order. Same config, same answer twice --
        and derivable from the config without running anything."""
        assert clear(self._without("D"))["slack"] == "A"
        assert clear(self._without("A", "D"))["slack"] == "B"
        assert clear(self._without("D"))["slack"] == "A"

    def test_deleting_some_other_bus_leaves_the_slack_alone(self):
        """The fallback fires only when the named slack is actually gone.

        Deleting bus A while D is the slack must not move it -- a slack that
        wandered on an unrelated edit would make lambda jump on screen for no
        reason a reader could see.
        """
        assert clear(self._without("A"))["slack"] == "D"

    def test_an_explicitly_named_slack_that_is_not_a_bus_still_raises(self):
        """The fallback is for a STALE RECORD, not for a wrong argument.

        slack= is an assertion by this caller about this call. A typo that
        silently answered about a different bus is how a sweep reports a day
        of the wrong lambda and nobody notices. The config's recorded slack is
        a different thing -- written at parse time and possibly stale by now --
        and that is the one the editor's delete makes wrong.
        """
        with pytest.raises(ValueError, match="slack 'Z' is not a bus"):
            clear(build_scenario(W1_CONFIG), slack="Z")

    def test_the_prices_do_not_move(self):
        """Trap 2, asserted where the fallback fires.

        The scenario whose recorded slack is gone must price exactly as it
        does when the fallback bus is named outright -- same LMPs, same
        dispatch, same settlement. Only lambda's level is the slack's to
        decide.
        """
        scenario = self._without("D")
        fallen_back = clear(scenario)
        named = clear(scenario, slack="A")
        assert fallen_back["slack"] == named["slack"] == "A"
        for bus in named["buses"]:
            assert fallen_back["lmp"][bus, PEAK_HOUR] == pytest.approx(
                named["lmp"][bus, PEAK_HOUR]
            )
        for t in named["hours"]:
            assert fallen_back["settlement"]["A", t]["residual"] == pytest.approx(
                0.0, abs=1e-6
            )

    def test_naming_a_different_slack_moves_lambda_and_no_price(self):
        """Trap 2 proper, on the cut-down network. lambda moves $30 on case5
        and no LMP moves at all."""
        scenario = self._without("D")
        a = clear(scenario, slack="A")
        b = clear(scenario, slack="B")
        assert a["lmbda"]["A", PEAK_HOUR] != pytest.approx(b["lmbda"]["B", PEAK_HOUR])
        for bus in a["buses"]:
            assert a["lmp"][bus, PEAK_HOUR] == pytest.approx(b["lmp"][bus, PEAK_HOUR])


class TestAnIslandWithNothingInIt:
    """*Add bus* and nothing else: an island with no generator, no load, no line.

    The one-move version of the case W1 named under "an island with generation
    and no load is degenerate". This one has nothing on either side, so the
    balance row is 0 == 0 -- resolved in _balance as Constraint.Feasible -- and
    lambda sits anywhere at all. The solver hands back -0.0.

    What matters is not the number but that the flag says so, because the
    views read the flag and print the number. Before W3.9 the LMP panel, the
    settlement ledger and the network map all printed a bare $0.00 and the
    map's ramp inked it the cheapest bus on the page. The frontend asserts its
    own half in web/check-views.html; this is the field it reads.

    Every hour, not some hour. The domain the map's ramp is drawn over is
    taken across the whole day, so scales.js drops a bus only when no hour of
    it carries a readable price -- and that rule is only sound because a bus
    with no market is an interval in all 24, while an ordinary degenerate
    breakpoint is a few hours of the twenty-four.
    """

    @pytest.fixture(scope="class")
    def cleared(self):
        config = load_config(W1_CONFIG)
        config["network"]["buses"].append("Z")
        return clear(scenario_from_config(config), slack="D")

    def test_the_empty_bus_is_its_own_island(self, cleared):
        assert cleared["islands"]["Z"] == ["Z"]
        assert cleared["island_of"]["Z"] == "Z"

    def test_it_prices_at_nothing_in_particular(self, cleared):
        assert cleared["lmbda"]["Z", PEAK_HOUR] == pytest.approx(0.0, abs=1e-9)
        assert cleared["lmp"]["Z", PEAK_HOUR] == pytest.approx(0.0, abs=1e-9)

    def test_and_says_so_in_every_hour(self, cleared):
        verdicts = {cleared["uniqueness"]["Z", t]["verdict"] for t in range(24)}
        assert verdicts == {"price_is_an_interval"}

    def test_the_real_island_is_unaffected(self, cleared):
        """The empty bus is a separate market and moves no price in the other.

        Which is what makes dropping it from the map's colour domain a
        correction rather than a second answer: the prices it was distorting
        are the same prices they were before it existed.
        """
        base = clear(scenario_from_config(load_config(W1_CONFIG)), slack="D")
        for bus in base["buses"]:
            assert cleared["lmp"][bus, PEAK_HOUR] == pytest.approx(
                base["lmp"][bus, PEAK_HOUR]
            )
        for t in range(24):
            assert cleared["uniqueness"]["D", t]["verdict"] == (
                base["uniqueness"]["D", t]["verdict"]
            )


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
