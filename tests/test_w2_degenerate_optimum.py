"""A degenerate optimum that is reproducible, and its control one hour away.

Scoped at W2.9, which decided that clear() would carry a per-island, per-hour
uniqueness flag. This file is the pair of hours it has to get right, banked
before the code. The flag landed at W3.1 and is asserted against them at the
bottom of this file.

    configs/w1.yaml, both line limits removed, hour 8

Hour 8's load lands exactly on 40 + 170 + 600 = 810 MW -- alta, park_city and
brighton's capacities summed. No generator is left strictly between its bounds,
so no offer is the price, and the market clears at any lambda in [15, 30]: at
every one of those prices the same three units run flat out and solitude stays
off. The solver returns 15.0000 and says nothing about the other end.

Hour 7 is the control. Same config, same solve, 730 MW, park_city part-loaded
at 90 of 170, and lambda = 15 is the only answer.

What this fixture CANNOT do, measured rather than assumed: flake the slack
assertion. test_w2_editor.py notes that the slack test would flake on a
degenerate fixture, which is trap 2 against trap 3, and that claim is still
untested. It is not testable here. Swept over 1201 settings of the DE limit
and all 24 hours, the only degenerate pattern this scenario reaches is an
uncongested one -- basic 0 against 1 row -- and trap 2 already records that
lambda does not move with the slack unless a line binds. Measured directly
below: all five slacks return 15.0000 at hour 8. A fixture that is degenerate
AND congested would need a different scenario, and finding one is not this
file's job.
"""

import copy

import pytest

from src.ingest.scenario import load_config, scenario_from_config
from src.model.clearing import clear

W1_CONFIG = "configs/w1.yaml"

BREAKPOINT_HOUR = 8      # load lands exactly on 810 MW
CONTROL_HOUR = 7         # 730 MW, park_city part-loaded

TIED_HOURS = [20, 21]    # of the tied fixture below: two units interior at $25

LOWER = 15.0             # park_city's offer, the left slope of the cost curve
UPPER = 30.0             # solitude's offer, the right slope


def _unlimited(scenario):
    """Every branch rating removed, which is one drag of each limit slider."""
    return {br.name: float("inf") for br in scenario.branches}


def _scaled(config, k):
    """The same config with every bid's peak scaled, to walk load across 810."""
    out = copy.deepcopy(config)
    for bid in out["load"]["bids"].values():
        bid["peak_mw"] *= k
    return out


def _counts(cleared, hour):
    """(basic, rows) for the single island, the W2.9 detector written out.

        basic = generators strictly inside their bounds
              + bids strictly between 0 and their quantity
        rows  = 1 + lines with a non-zero mu

    One basic variable is needed per active row. Short, and a row has no
    variable free to set its price, so that price is an interval.
    """
    island = next(iter(cleared["islands"]))
    bids = {name for name, _ in cleared["served"]}
    interior = sum(
        1 for g in cleared["gen_bus"] if cleared["gen_status"][g, hour] == "interior"
    )
    partial = sum(
        1
        for b in bids
        if 1e-6 < cleared["served"][b, hour] < cleared["bid_mw"][b, hour] - 1e-6
    )
    binding = sum(1 for l in cleared["lines"] if abs(cleared["mu"][l, hour]) > 1e-9)
    return interior + partial, 1 + binding


@pytest.fixture(scope="module")
def config():
    return load_config(W1_CONFIG)


@pytest.fixture(scope="module")
def cleared(config):
    scenario = scenario_from_config(config)
    return clear(scenario, slack="D", limits=_unlimited(scenario))


class TestTheBreakpointHourIsDegenerate:
    """What the W3 flag has to return true for."""

    def test_no_generator_is_part_loaded(self, cleared):
        for g in cleared["gen_bus"]:
            assert cleared["gen_status"][g, BREAKPOINT_HOUR] in ("off", "at_max"), g

    def test_load_lands_exactly_on_a_capacity_breakpoint(self, cleared):
        served = sum(
            cleared["served"][b, BREAKPOINT_HOUR]
            for b in {name for name, _ in cleared["served"]}
        )
        running = ["alta", "park_city", "brighton"]
        assert served == pytest.approx(sum(cleared["gen_pmax"][g] for g in running))
        assert served == pytest.approx(810.0)

    def test_a_row_has_no_variable_to_set_its_price(self, cleared):
        basic, rows = _counts(cleared, BREAKPOINT_HOUR)
        assert (basic, rows) == (0, 1)

    def test_park_city_is_full_and_indifferent_at_once(self, cleared):
        # The case reduced_costs() documents: at_max with a reduced cost of
        # zero is not a contradiction, it is the breakpoint.
        assert cleared["gen_status"]["park_city", BREAKPOINT_HOUR] == "at_max"
        assert cleared["reduced_cost"]["park_city", BREAKPOINT_HOUR] == pytest.approx(0.0)


class TestTheControlHourIsNot:
    """What the W3 flag has to return false for, one hour away in one solve."""

    def test_park_city_is_part_loaded(self, cleared):
        assert cleared["gen_status"]["park_city", CONTROL_HOUR] == "interior"
        assert cleared["dispatch"]["park_city", CONTROL_HOUR] == pytest.approx(90.0)

    def test_one_variable_sets_the_one_row(self, cleared):
        assert _counts(cleared, CONTROL_HOUR) == (1, 1)

    def test_the_price_is_the_part_loaded_units_offer(self, cleared):
        assert cleared["lmbda"]["D", CONTROL_HOUR] == pytest.approx(LOWER)


class TestTheIntervalIsFifteenToThirty:
    """The interval measured the way it is defined: as the two slopes of the
    total cost curve either side of the kink.

    Scaling every bid walks the load across 810 MW. Below the breakpoint
    park_city is part-loaded and the next MW costs its offer; above it,
    solitude is, and the next MW costs 30. At 810 the curve has a corner and
    the supporting slopes are the whole closed interval between them.

    W2.9 deferred PRINTING this interval to W4. The measurement is here so
    that decision can be made without re-deriving it.
    """

    @pytest.fixture(scope="class")
    def sides(self, config):
        out = {}
        for label, k in (("below", 0.995), ("above", 1.005)):
            scenario = scenario_from_config(_scaled(config, k))
            out[label] = clear(scenario, slack="D", limits=_unlimited(scenario))
        return out

    def test_below_the_breakpoint_the_price_is_the_lower_end(self, sides):
        assert sides["below"]["lmbda"]["D", BREAKPOINT_HOUR] == pytest.approx(LOWER)

    def test_above_the_breakpoint_the_price_is_the_upper_end(self, sides):
        assert sides["above"]["lmbda"]["D", BREAKPOINT_HOUR] == pytest.approx(UPPER)

    def test_the_returned_price_is_one_end_of_the_interval(self, cleared):
        # Which end is the solver's pivot order, not the market's answer. The
        # assertion is membership, deliberately: an engine that returned the
        # other end would be equally correct, and a test pinning 15 would fail
        # on a solver upgrade for no reason a reader could act on.
        lmbda = cleared["lmbda"]["D", BREAKPOINT_HOUR]
        assert LOWER <= lmbda <= UPPER
        assert lmbda in (pytest.approx(LOWER), pytest.approx(UPPER))


class TestDegeneracyBreaksNoInvariant:
    """The forever-true statements, asserted at the breakpoint because that is
    where a reader would doubt them. An ambiguous price is still a consistent
    one: every member of the interval settles."""

    def test_the_settlement_identity_holds_at_the_breakpoint(self, cleared):
        entry = cleared["settlement"]["D", BREAKPOINT_HOUR]
        assert entry["residual"] == pytest.approx(0.0, abs=1e-6)

    def test_every_bus_prices_at_the_same_number_with_nothing_congested(self, cleared):
        for bus in cleared["buses"]:
            assert cleared["lmp"][bus, BREAKPOINT_HOUR] == pytest.approx(
                cleared["lmbda"]["D", BREAKPOINT_HOUR]
            )

    def test_the_slack_does_not_move_the_price_here(self, config):
        """Measured, and it is why this fixture cannot flake the slack test.

        Trap 2: lambda moves with the slack only where a line binds. Nothing
        binds at hour 8 with the limits off, so all five slacks agree -- the
        degeneracy is real and invisible to the slack lever.
        """
        scenario = scenario_from_config(config)
        limits = _unlimited(scenario)
        prices = {
            slack: clear(scenario, slack=slack, limits=limits)["lmbda"][
                slack, BREAKPOINT_HOUR
            ]
            for slack in [b.name for b in scenario.buses]
        }
        assert set(prices) == {"A", "B", "C", "D", "E"}
        for slack, lmbda in prices.items():
            assert lmbda == pytest.approx(LOWER), slack


class TestTheFlagSaysWhichHalfIsNotPinned:
    """W3.1. clear() carries the count, and it agrees with the hours above.

    Every number the flag reads is one clear() already returns, so this costs
    no extra solve. What is asserted here is the comparison, on the two hours
    this file was written to bank.
    """

    def test_the_breakpoint_hour_says_the_price_is_an_interval(self, cleared):
        assert cleared["uniqueness"]["D", BREAKPOINT_HOUR]["verdict"] == (
            "price_is_an_interval"
        )

    def test_and_reports_the_count_that_says_so(self, cleared):
        flag = cleared["uniqueness"]["D", BREAKPOINT_HOUR]
        assert (flag["basic"], flag["rows"]) == (0, 1)

    def test_the_control_hour_is_pinned(self, cleared):
        flag = cleared["uniqueness"]["D", CONTROL_HOUR]
        assert flag["verdict"] == "unique"
        assert (flag["basic"], flag["rows"]) == (1, 1)

    def test_the_flag_agrees_with_the_helper_this_file_already_had(self, cleared):
        """_counts is the same comparison written by hand at W2.9.

        It is kept as an independent statement of the rule: if the engine's
        version and this file's version ever disagree, one of them has been
        edited without the other.
        """
        for hour in (CONTROL_HOUR, BREAKPOINT_HOUR):
            basic, rows = _counts(cleared, hour)
            flag = cleared["uniqueness"]["D", hour]
            assert (flag["basic"], flag["rows"]) == (basic, rows)

    def test_every_island_and_hour_carries_one(self, cleared):
        keys = {(home, t) for home in cleared["islands"] for t in cleared["hours"]}
        assert set(cleared["uniqueness"]) == keys


class TestTheOtherDegeneracyIsADifferentSentence:
    """basic > rows: the price is pinned and who runs is not.

    The two directions do not collapse into one "degenerate" bool, and this
    is the half that would be lost if they did. Reached by giving two units
    the same offer with nothing congested, so a MW can move between them at
    no cost -- the dispatch table under trap 2, in miniature.
    """

    @pytest.fixture(scope="class")
    def tied(self, config):
        """Three units at $25 and two lines rated, found by sweeping offers
        and ratings rather than reasoned out.

        Equal offers alone do not reach it: with every unit at $25 and one
        capacity for all five, the solver loads them in order and exactly one
        lands interior, so the count is 1 against 1 and says "unique" -- which
        it is, as a statement about the price. It takes two units able to be
        part-loaded at once, which is what the AD and DE ratings arrange here.
        """
        out = copy.deepcopy(config)
        offers = {
            "alta": (25.0, 100.0),
            "park_city": (25.0, 600.0),
            "solitude": (10.0, 40.0),
            "sundance": (30.0, 40.0),
            "brighton": (25.0, 520.0),
        }
        for name, (cost, pmax) in offers.items():
            out["fleet"][name]["cost_usd_per_mwh"] = cost
            out["fleet"][name]["pmax_mw"] = pmax
        scenario = scenario_from_config(out)
        return clear(scenario, slack="D", limits={"AD": 400.0, "DE": 240.0})

    def test_some_hour_has_more_basic_units_than_rows(self, tied):
        assert self._ambiguous(tied) == TIED_HOURS

    @staticmethod
    def _ambiguous(tied):
        return [
            t
            for t in tied["hours"]
            if tied["uniqueness"]["D", t]["verdict"] == "dispatch_is_not_unique"
        ]

    def test_and_there_the_tied_units_share_an_offer_at_zero_reduced_cost(self, tied):
        for t in self._ambiguous(tied):
            inside = [
                g for g in tied["gen_bus"] if tied["gen_status"][g, t] == "interior"
            ]
            assert len(inside) > 1
            assert len({tied["gen_cost"][g] for g in inside}) == 1
            for g in inside:
                assert tied["reduced_cost"][g, t] == pytest.approx(0.0, abs=1e-9)

    def test_the_price_itself_is_not_in_doubt_there(self, tied):
        """The count is above the rows, not below, so no dual has room."""
        for t in self._ambiguous(tied):
            flag = tied["uniqueness"]["D", t]
            assert flag["basic"] > flag["rows"]
