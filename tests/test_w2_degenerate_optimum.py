"""A degenerate optimum that is reproducible, and its control one hour away.

Scoped at W2.9, which decided that clear() would carry a per-island, per-hour
uniqueness flag. This file is the pair of hours it has to get right, banked
before the code. The flag landed at W3.1 and is asserted against them at the
bottom of this file.

    configs/w1.yaml, both line limits removed, hour 8

Hour 8's load lands exactly on 40 + 170 + 600 = 810 MW -- A1, A2 and
E1's capacities summed. No generator is left strictly between its bounds,
so no offer is the price, and the market clears at any lambda in [15, 30]: at
every one of those prices the same three units run flat out and C1 stays
off. The solver returns 15.0000 and says nothing about the other end.

Hour 7 is the control. Same config, same solve, 730 MW, A2 part-loaded
at 90 of 170, and lambda = 15 is the only answer.

What this fixture CANNOT do, measured rather than assumed: flake the slack
assertion. test_w2_editor.py notes that the slack test would flake on a
degenerate fixture, which is trap 2 against trap 3, and that claim is still
untested. It is not testable here, and the reason is sharper than it was.

The DE sweep that first asked this walked 1201 ratings on a 1 MW grid and
found only basic 0 against 1 row. A grid cannot land on 282.84033120469894,
which is the flow DE carries when nothing is rated, and rating it there is a
second degenerate pattern -- basic 1 against 2 rows, banked below. So "the
only pattern this scenario reaches" was a statement about the grid.

The conclusion survives anyway, for a reason that is about the market rather
than about the sample. Both patterns are UNCONGESTED: mu is zero at each, so
every bus prices at lambda and trap 2 says lambda does not move with the
slack unless a line binds. Measured, all five slacks: 15.0000 at hour 8,
30.0000 at the pinned point. A fixture that is degenerate AND carries a
non-zero mu would need a different scenario, and finding one is still open.
"""

import copy
import itertools

import pytest

from src.ingest.scenario import load_config, scenario_from_config
from src.model.clearing import clear

W1_CONFIG = "configs/w1.yaml"

BREAKPOINT_HOUR = 8      # load lands exactly on 810 MW
PINNED_HOUR = 18         # the day's peak, where DE carries the most
CONTROL_HOUR = 7         # 730 MW, A2 part-loaded

# Of the tied fixture below. Verified against ground truth rather than read
# off the flag: at each of these an alternative optimal dispatch was found by
# perturbing one offer by +/-1e-4 and scoring the answer at the true offers,
# and at the other eight hours none exists. The flag agrees on all 24.
TIED_HOURS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 20, 21, 22, 23]

LOWER = 15.0             # A2's offer, the left slope of the cost curve
UPPER = 30.0             # C1's offer, the right slope


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
        running = ["A1", "A2", "E1"]
        assert served == pytest.approx(sum(cleared["gen_pmax"][g] for g in running))
        assert served == pytest.approx(810.0)

    def test_a_row_has_no_variable_to_set_its_price(self, cleared):
        basic, rows = _counts(cleared, BREAKPOINT_HOUR)
        assert (basic, rows) == (0, 1)

    def test_a2_is_full_and_indifferent_at_once(self, cleared):
        # The case reduced_costs() documents: at_max with a reduced cost of
        # zero is not a contradiction, it is the breakpoint.
        assert cleared["gen_status"]["A2", BREAKPOINT_HOUR] == "at_max"
        assert cleared["reduced_cost"]["A2", BREAKPOINT_HOUR] == pytest.approx(0.0)


class TestTheControlHourIsNot:
    """What the W3 flag has to return false for, one hour away in one solve."""

    def test_a2_is_part_loaded(self, cleared):
        assert cleared["gen_status"]["A2", CONTROL_HOUR] == "interior"
        assert cleared["dispatch"]["A2", CONTROL_HOUR] == pytest.approx(90.0)

    def test_one_variable_sets_the_one_row(self, cleared):
        assert _counts(cleared, CONTROL_HOUR) == (1, 1)

    def test_the_price_is_the_part_loaded_units_offer(self, cleared):
        assert cleared["lmbda"]["D", CONTROL_HOUR] == pytest.approx(LOWER)


class TestTheIntervalIsFifteenToThirty:
    """The interval measured the way it is defined: as the two slopes of the
    total cost curve either side of the kink.

    Scaling every bid walks the load across 810 MW. Below the breakpoint
    A2 is part-loaded and the next MW costs its offer; above it,
    C1 is, and the next MW costs 30. At 810 the curve has a corner and
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
    """The price is pinned and who runs is not.

    The two directions do not collapse into one "degenerate" bool, and this
    is the half that would be lost if they did. Reached by giving three units
    the same offer, so a MW can move between them at no cost -- the dispatch
    table under trap 2, in miniature.

    The mechanism is a variable sitting AT a bound with a reduced cost of
    zero, which is `tied` in the flag. It is NOT basic > rows: that was what
    this class asserted while price_uniqueness counted an active row by
    mu != 0, and a saturated line carrying mu = 0 was then missed, which
    inflated basic above rows and produced the right verdict from the wrong
    arithmetic. Counting rows from the primal removed the accident; the tied
    count is what actually detects this.
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
            "A1": (25.0, 100.0),
            "A2": (25.0, 600.0),
            "C1": (10.0, 40.0),
            "D1": (30.0, 40.0),
            "E1": (25.0, 520.0),
        }
        for name, (cost, pmax) in offers.items():
            out["fleet"][name]["cost_usd_per_mwh"] = cost
            out["fleet"][name]["pmax_mw"] = pmax
        scenario = scenario_from_config(out)
        return clear(scenario, slack="D", limits={"AD": 400.0, "DE": 240.0})

    def test_the_flag_finds_every_hour_with_an_alternative_optimum(self, tied):
        assert self._ambiguous(tied) == TIED_HOURS

    @staticmethod
    def _ambiguous(tied):
        return [
            t
            for t in tied["hours"]
            if tied["uniqueness"]["D", t]["verdict"] == "dispatch_is_not_unique"
        ]

    def test_and_there_a_unit_sits_at_a_bound_it_is_indifferent_about(self, tied):
        """What the verdict is drawn from: a unit off or full, at zero margin.

        Zero margin is the whole content. A unit at a bound cannot move on the
        side the bound is on, but a reduced cost of zero says the objective
        does not care if it moves on the other, so the answer is one of
        several and nothing in the money chooses between them.
        """
        for t in self._ambiguous(tied):
            flag = tied["uniqueness"]["D", t]
            assert flag["tied"] > 0
            at_bounds = [
                g
                for g in tied["gen_bus"]
                if tied["gen_status"][g, t] != "interior"
                and tied["reduced_cost"][g, t] == pytest.approx(0.0, abs=1e-9)
            ]
            assert len(at_bounds) == flag["tied"]
            # Indifferent because it shares the clearing offer, not by accident.
            for g in at_bounds:
                assert tied["gen_cost"][g] == pytest.approx(25.0)

    def test_the_price_itself_is_not_in_doubt_there(self, tied):
        """No row is left without a variable to pin it, so no dual has room.

        The gate the tied count is read behind: a reduced cost is measured
        against lambda, so where lambda is an interval a zero carries no
        information. basic >= rows at every one of these hours, which is what
        makes the zeros above mean what they are read to mean.
        """
        for t in self._ambiguous(tied):
            flag = tied["uniqueness"]["D", t]
            assert flag["basic"] >= flag["rows"]



def _slopes(cleared, rating, bus, delta=0.01):
    """dCost/dLoad at a bus, from each side. The LMP's own definition.

    Returns (from below, from above). A kink in the cost curve has no single
    slope, and the two supporting slopes either side of it ARE the interval
    the price is drawn from -- which is how a claim about duals is checked
    against the primal instead of against itself.
    """
    config = load_config(W1_CONFIG)
    scenario = scenario_from_config(config)
    free = {b.name: float("inf") for b in scenario.branches}
    limits = {**free, "DE": rating}
    shape = config["load"]["shape"][PINNED_HOUR]

    def at(shift):
        out = copy.deepcopy(config)
        for bid in out["load"]["bids"].values():
            if bid["bus"] == bus:
                bid["peak_mw"] += shift / shape
                break
        run = clear(scenario_from_config(out), slack="D", limits=limits)
        served = sum(run["served"][k, PINNED_HOUR] for k in run["bid_bus"])
        cost = sum(
            run["gen_cost"][g] * run["dispatch"][g, PINNED_HOUR]
            for g in run["gen_bus"]
        )
        return cost, served

    (c0, s0), (cm, sm), (cp, sp) = at(0.0), at(-delta), at(+delta)
    return (c0 - cm) / (s0 - sm), (cp - c0) / (sp - s0)

class TestALineAtItsRatingHoldsARowEvenWithNoMu:
    """W3.8. An active row the dual cannot see, and the price it hides.

    A flow limit can be exactly satisfied with mu = 0. The row is active --
    it holds the dispatch where it is -- but it carries no rent, so a count
    that asks "which lines have a non-zero mu" misses it, under-counts rows,
    and reports a unique price at exactly the knife edge the flag exists to
    find.

    Reachable in one move from the editor, and reproducible without a magic
    number: solve the network unrated, read DE's own flow back, and rate DE
    at it. The constraint is then satisfied with nothing to spare and the
    dispatch cannot move, so the dual is free.
    """

    @pytest.fixture(scope="class")
    def pinned(self, config):
        scenario = scenario_from_config(config)
        free = {b.name: float("inf") for b in scenario.branches}
        loose = clear(scenario, slack="D", limits=free)
        rating = abs(loose["flows"]["DE", PINNED_HOUR])
        return clear(scenario, slack="D", limits={**free, "DE": rating}), rating

    def test_the_line_sits_on_its_rating_carrying_no_rent(self, pinned):
        cleared, rating = pinned
        assert abs(cleared["flows"]["DE", PINNED_HOUR]) == pytest.approx(rating, abs=1e-9)
        assert cleared["mu"]["DE", PINNED_HOUR] == pytest.approx(0.0, abs=1e-9)

    def test_and_the_row_is_counted_anyway(self, pinned):
        cleared, _ = pinned
        flag = cleared["uniqueness"]["D", PINNED_HOUR]
        assert flag == {
            "basic": 1,
            "rows": 2,
            "tied": 0,
            "verdict": "price_is_an_interval",
        }

    def test_because_the_price_there_really_is_an_interval(self, pinned):
        """The claim the flag makes, checked against the cost curve itself.

        The LMP at a bus is the derivative of production cost with respect to
        load there. Measured either side of the solved point, bus D:

            from below   30.0000        the engine returns 30.0000
            from above   39.9427

        A convex kink has no single slope, and both are supporting slopes.
        Asserted at a tolerance far above the perturbation's own error and
        far below the $9.94 gap.
        """
        cleared, rating = pinned
        left, right = _slopes(cleared, rating, bus="D")
        assert left == pytest.approx(30.0, abs=1e-3)
        assert right == pytest.approx(39.9427, abs=1e-3)
        assert right - left > 9.0

    def test_and_it_still_cannot_flake_the_slack_assertion(self, pinned):
        """Degenerate and sitting on a rating, but not congested.

        The fixture that would put trap 2 against trap 3 needs a degenerate
        optimum where a line actually BINDS, and this is not it: mu is zero,
        so every bus prices at lambda and trap 2 says lambda does not move.
        Measured, all five slacks at this point.
        """
        _, rating = pinned
        scenario = scenario_from_config(load_config(W1_CONFIG))
        free = {b.name: float("inf") for b in scenario.branches}
        for slack in ("A", "B", "C", "D", "E"):
            out = clear(scenario, slack=slack, limits={**free, "DE": rating})
            assert out["lmbda"][slack, PINNED_HOUR] == pytest.approx(30.0, abs=1e-9)
            assert out["uniqueness"][slack, PINNED_HOUR]["verdict"] == (
                "price_is_an_interval"
            )


class TestAShortageDoesNotChooseWhoIsShed:
    """W3.8. Firm bids at one valuation, and a curtailment that is arbitrary.

    Every bid in configs/w1.yaml is firm at the offer cap, so when capacity
    falls short the market is indifferent about WHICH load it sheds -- the
    welfare lost is the same MW at the same price whoever loses it. The
    solver picks one and the page draws it. The flag has to say so.

    One lever reaches it: E1 is 600 MW of the fleet's 1530, and hour 18 asks
    for 1000.
    """

    @pytest.fixture(scope="class")
    def short(self, config):
        out = copy.deepcopy(config)
        out["fleet"]["E1"]["pmax_mw"] = 0.0
        return clear(scenario_from_config(out), slack="D")

    def test_load_is_actually_shed(self, short):
        asked = sum(short["bid_mw"][k, PINNED_HOUR] for k in short["bid_bus"])
        got = sum(short["served"][k, PINNED_HOUR] for k in short["bid_bus"])
        assert asked - got == pytest.approx(70.0, abs=1e-6)

    def test_and_the_flag_says_the_dispatch_is_not_unique(self, short):
        flag = short["uniqueness"]["D", PINNED_HOUR]
        assert flag["verdict"] == "dispatch_is_not_unique"
        assert flag["tied"] > 0

    def test_because_relabelling_the_bids_sheds_a_different_one(self, config):
        """The property the flag is standing in for, demonstrated directly.

        Six orderings of the same three bids, identical welfare to the cent,
        three different answers to who goes dark. Nothing in the money
        chooses between them; only the order they appear in the config does.
        """
        names = list(config["load"]["bids"])
        welfare, shed = set(), set()
        for order in itertools.permutations(names):
            out = copy.deepcopy(config)
            out["fleet"]["E1"]["pmax_mw"] = 0.0
            out["load"]["bids"] = {k: out["load"]["bids"][k] for k in order}
            r = clear(scenario_from_config(out), slack="D")
            benefit = sum(
                r["bid_value"][k] * r["served"][k, PINNED_HOUR] for k in names
            )
            cost = sum(
                r["gen_cost"][g] * r["dispatch"][g, PINNED_HOUR] for g in r["gen_bus"]
            )
            welfare.add(round(benefit - cost, 6))
            shed.add(
                tuple(
                    sorted(
                        k
                        for k in names
                        if r["served"][k, PINNED_HOUR]
                        < r["bid_mw"][k, PINNED_HOUR] - 1e-6
                    )
                )
            )
        assert len(welfare) == 1
        assert len(shed) == 3
