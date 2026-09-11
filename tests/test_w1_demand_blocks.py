r"""W1: demand becomes a named, priced participant.

The scaffolding is here and the FORMULATION IS NOT. That split is deliberate,
and this file is the specification for the half that is missing.

    written                              not written
    -------                              -----------
    DemandBid(name, bus, mw, value)      the LP reading `value`
    load.source: blocks                  d[bid, t] as a VARIABLE
    configs/w1.yaml                      the benefit term in the objective
    every test below                     the balance RHS becoming a sum of vars

So today src/model/dispatch.py still sums every bid into a fixed right-hand
side and ignores the price entirely -- which is exactly why configs/w1.yaml
must clear to configs/m4.yaml's answer bit for bit. That equality is the
control:

    m4.yaml  ──┐
               ├──> clear() ──> IDENTICAL, every field, every hour
    w1.yaml  ──┘

    demand is data          demand is a named bid at $5000
                            (and $5000 beats every offer, so it is all served)

Two tests are marked xfail(strict=True). They are not broken; they are the
statement of what the formulation must do, and they will XPASS -- and so fail
the suite, loudly -- the moment it is written. Delete the marker then.

Grouped by lifespan. TestBitIdentity must hold forever: an elastic demand
side that changes the answer for INELASTIC load is a bug, whatever else it
gets right.
"""

import math

import pytest

from src.ingest.scenario import build_scenario, load_config, scenario_from_config
from src.model.clearing import clear
from src.model.inputs import DemandBid

M4_CONFIG = "configs/m4.yaml"
W1_CONFIG = "configs/w1.yaml"
PEAK_HOUR = 18

# The published PJM 5-bus LMPs, as tests/test_m3_network.py asserts them.
PUBLISHED_LMP = {"A": 16.9774, "B": 26.3845, "C": 30.0000, "D": 39.9427, "E": 10.0000}


@pytest.fixture(scope="module")
def m4():
    return clear(build_scenario(M4_CONFIG))


@pytest.fixture(scope="module")
def w1():
    return clear(build_scenario(W1_CONFIG))


# ------------------------------------------------------------- the control


class TestBitIdentity:
    """Naming and pricing demand changes no number. Forever.

    Every firm bid is valued at the offer cap, which is above every offer in
    the fleet, so the market serves all of it and the answer is m4's. This
    holds today because the LP ignores the price, and it must STILL hold once
    the LP reads it -- for a different reason, which is the real content of
    the test: a bid nobody can outbid is served in full.
    """

    @pytest.mark.parametrize(
        "field", ["dispatch", "flows", "mu", "lmp", "congestion", "reduced_cost"]
    )
    def test_every_series_is_identical_to_m4(self, w1, m4, field):
        assert set(w1[field]) == set(m4[field])
        for key, value in m4[field].items():
            assert w1[field][key] == pytest.approx(value), key

    def test_prices_and_cost_are_identical(self, w1, m4):
        assert w1["cost"] == pytest.approx(m4["cost"])
        for t in m4["hours"]:
            assert w1["lmbda"]["D", t] == pytest.approx(m4["lmbda"]["D", t])

    def test_the_published_lmps_survive(self, w1):
        """M3's regression test, through the new ingest path."""
        for bus, expected in PUBLISHED_LMP.items():
            assert w1["lmp"][bus, PEAK_HOUR] == pytest.approx(expected, abs=1e-4)

    def test_the_settlement_identity_holds_every_hour(self, w1):
        for t in w1["hours"]:
            assert w1["settlement"]["D", t]["residual"] == pytest.approx(0.0, abs=1e-6)

    def test_the_network_and_fleet_blocks_still_match_m4(self):
        """Guards the verbatim copy, the same way M4 guards its copy of M3.

        A reactance edited in one file and not the other would leave the bit
        identity test comparing two different networks and passing anyway.
        """
        m4c, w1c = load_config(M4_CONFIG), load_config(W1_CONFIG)
        assert w1c["network"] == m4c["network"]
        assert w1c["fleet"] == m4c["fleet"]
        assert w1c["load"]["shape"] == m4c["load"]["shape"]

    def test_the_peaks_match_m4s_per_bus_load(self):
        """The bids restate m4's peak_mw and do not quietly rescale it."""
        m4c, w1c = load_config(M4_CONFIG), load_config(W1_CONFIG)
        by_bus = {}
        for bid in w1c["load"]["bids"].values():
            by_bus[bid["bus"]] = by_bus.get(bid["bus"], 0.0) + bid["peak_mw"]
        assert by_bus == m4c["load"]["peak_mw"]


# ------------------------------------------------------------ the data model


class TestDemandBid:
    """A bid is a generator with the sign flipped, and validates like one."""

    def test_a_bid_without_a_value_is_inelastic(self):
        bid = DemandBid("B_firm", "B", {0: 100.0})
        assert bid.value_usd_per_mwh is None
        assert not bid.elastic

    def test_a_priced_bid_is_elastic(self):
        assert DemandBid("dr", "B", {0: 80.0}, 300.0).elastic

    def test_a_negative_value_is_refused(self):
        with pytest.raises(ValueError, match="value_usd_per_mwh"):
            DemandBid("dr", "B", {0: 80.0}, -1.0)

    def test_negative_demand_is_refused(self):
        with pytest.raises(ValueError, match="negative demand"):
            DemandBid("dr", "B", {0: -80.0})

    def test_two_bids_at_one_bus_are_a_demand_curve_not_an_error(self):
        """The single most important thing this design buys.

        An anonymous per-bus block cannot express a second, lower-valued slice
        of demand at the same bus. A named one can, and that slice is demand
        response.
        """
        config = load_config(W1_CONFIG)
        config["load"]["bids"]["B_datacenter"] = {
            "bus": "B", "peak_mw": 80.0, "value_usd_per_mwh": 300.0
        }
        scenario = scenario_from_config(config, origin="<test>")
        assert scenario.demand_by_bus()["B"][PEAK_HOUR] == pytest.approx(380.0)
        assert scenario.bid_bus()["B_datacenter"] == "B"
        assert scenario.bid_value()["B_datacenter"] == 300.0

    def test_duplicate_bid_names_are_refused(self):
        scenario = build_scenario(W1_CONFIG)
        with pytest.raises(ValueError, match="duplicate demand bid names"):
            type(scenario)(
                name="dupe",
                generators=scenario.generators,
                bids=scenario.bids + (scenario.bids[0],),
                buses=scenario.buses,
                branches=scenario.branches,
            )


class TestBlocksConfig:
    """The blocks source owns its own validation and inherits no guard."""

    def _config(self, **load):
        config = load_config(W1_CONFIG)
        config["load"].update(load)
        return config

    def test_a_bid_must_declare_what_it_will_pay(self):
        """The whole point of opting into blocks. A bid with no price is a
        block whose author has not decided what it is worth."""
        config = self._config()
        del config["load"]["bids"]["B_firm"]["value_usd_per_mwh"]
        with pytest.raises(ValueError, match="value_usd_per_mwh is required"):
            scenario_from_config(config, origin="<test>")

    def test_a_bid_must_declare_a_bus(self):
        config = self._config()
        del config["load"]["bids"]["B_firm"]["bus"]
        with pytest.raises(ValueError, match="no bus"):
            scenario_from_config(config, origin="<test>")

    def test_a_bid_at_an_undeclared_bus_is_refused(self):
        config = self._config()
        config["load"]["bids"]["B_firm"]["bus"] = "Z"
        with pytest.raises(ValueError, match="unknown bus"):
            clear(scenario_from_config(config, origin="<test>"))

    def test_empty_bids(self):
        with pytest.raises(ValueError, match="no demand to serve"):
            scenario_from_config(self._config(bids={}), origin="<test>")

    def test_the_shape_guard_is_shared_with_the_profile_source(self):
        """Not a second copy. A shape peaking at 0.95 silently rescales every
        bid, and both sources must refuse it for the same reason."""
        with pytest.raises(ValueError, match="must peak at exactly 1.0"):
            scenario_from_config(self._config(shape=[0.5, 0.95]), origin="<test>")

    def test_hours_are_integers_as_at_m4(self):
        assert build_scenario(W1_CONFIG).hours == list(range(24))


# ------------------------------------------------- the formulation, specified


class TestElasticDemand:
    """The demand side, once dispatch.py reads a bid's price.

    These two were written as xfail(strict=True) BEFORE the formulation, as
    its specification, and the markers came off when they passed. They are
    kept exactly as written -- the whole value of a test written first is
    that it was not shaped around the implementation that satisfies it.

    The formulation, for reference. One variable, one changed constraint:

        d[k, t]                    0 <= d[k,t] <= mw[k,t]        NEW variable
        min  sum_g c[g]*p[g,t] - sum_k v[k]*d[k,t]                NEW term
        s.t. sum_g p[g,t] == sum_k d[k,t]                         RHS is now vars
             inj[i,t] = sum_{g at i} p - sum_{k at i} d           d, not D

    The trap is settlement: payments must be computed on SERVED demand, not on
    declared. Re-derive payments - revenue = -sum_l mu[l]*f[l] with d in the
    injection before writing it; the benefit term drops out, but the identity
    is only worth anything because it was derived rather than assumed.
    """

    def _shortfall(self):
        """m4's day, with a fleet far too small to serve it."""
        config = load_config(W1_CONFIG)
        for spec in config["fleet"].values():
            spec["pmax_mw"] = 50.0
        return scenario_from_config(config, origin="<test>")

    def _cheap_bid(self):
        """A bid valued below every offer. No market would ever serve it."""
        config = load_config(W1_CONFIG)
        config["load"]["bids"]["B_interruptible"] = {
            "bus": "B", "peak_mw": 100.0, "value_usd_per_mwh": 5.0
        }
        return scenario_from_config(config, origin="<test>")

    def test_a_shortfall_prices_at_the_cap_instead_of_raising(self):
        """The answer to 'what does the engine say when load cannot be served'.

        It says the last MW was worth $5000 to someone who did not get it.
        lambda equals the highest valuation in the market, because the
        marginal resource is a consumer rather than a machine.
        """
        cleared = clear(self._shortfall())
        cap = max(build_scenario(W1_CONFIG).bid_value().values())
        assert cleared["lmbda"]["D", PEAK_HOUR] == pytest.approx(cap)

    def test_a_bid_below_the_clearing_price_is_not_served(self):
        """Demand response, with no code path of its own.

        A 100 MW bid at $5/MWh sits below Brighton's $10 offer, so it is never
        worth serving. Total dispatch must therefore be m4's, not m4's plus
        100 -- the market declined the bid on price alone.
        """
        cleared = clear(self._cheap_bid())
        served = sum(cleared["dispatch"][g, PEAK_HOUR] for g in cleared["gen_bus"])
        m4_demand = sum(
            build_scenario(M4_CONFIG).demand_by_bus()[b][PEAK_HOUR]
            for b in cleared["buses"]
        )
        assert served == pytest.approx(m4_demand)
        assert cleared["served"]["B_interruptible", PEAK_HOUR] == pytest.approx(0.0)

    def test_a_shortfall_still_settles(self):
        """The identity, in the hour the market could not serve everything.

        The trap this guards: load must be billed for what it TOOK, not for
        what it asked for. Bill declared demand while the injection carries
        served demand and the difference lands in the residual, where it
        reads like a PTDF sign error.
        """
        cleared = clear(self._shortfall())
        for t in cleared["hours"]:
            assert cleared["settlement"]["D", t]["residual"] == pytest.approx(0.0, abs=1e-6)

    def test_a_shortfall_serves_what_it_can(self):
        """Curtailment is partial, not all-or-nothing, and is priced."""
        cleared = clear(self._shortfall())
        served = sum(cleared["served"][k, PEAK_HOUR] for k in cleared["bid_value"])
        asked = sum(cleared["bid_mw"][k, PEAK_HOUR] for k in cleared["bid_value"])
        assert 0 < served < asked
        # Every generator is running flat out. Nothing was left unused while
        # demand went unserved.
        for g in cleared["gen_bus"]:
            assert cleared["gen_status"][g, PEAK_HOUR] == "at_max"
