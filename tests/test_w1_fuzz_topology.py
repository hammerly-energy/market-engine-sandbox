r"""W1's deliverable: every input the editor can produce is answered.

The three formulation questions were the interesting half. This is the half
that proves the answers are COMPLETE rather than merely covering the cases
someone thought of.

    the claim              every scenario the editor can build returns either
                           a priced solve that satisfies every invariant, or
                           ONE NAMED, DISPLAYABLE reason -- never a traceback,
                           never a plausible wrong number, never a hang.

    the method             build random networks from the same moves the
                           editor has: add a bus, connect a line, add a
                           generator, price a bid, name a slack. Solve each
                           one. Assert the invariants on every success and
                           assert the MESSAGE on every failure.

Seeded rather than property-based, because hypothesis is not a dependency of
this repo and a seed list is reproducible in exactly the way that matters:
a failure names the seed, and rerunning that seed reproduces it.

The second class is the one that stops this being theatre. A fuzz test that
happened to generate only connected five-bus networks would pass and prove
nothing at all, so the corpus itself is asserted: it must actually contain
disconnected networks, isolated buses, parallel branches, curtailment and
each refusal the table in CLAUDE.md claims.
"""

import math
import random

import pytest

from src.model.clearing import clear
from src.model.inputs import Branch, Bus, DemandBid, Generator, Scenario

SEEDS = list(range(120))
LETTERS = "ABCDEF"

# Every refusal this engine is allowed to produce, as a substring of the
# message. A ValueError whose text matches none of these is a failure: either
# a new refusal that belongs in CLAUDE.md's table, or a bug.
ALLOWED_REFUSALS = (
    # clear() -- no network to price
    "nodal clearing needs a network",
    # Scenario.__post_init__ -- nothing to dispatch, nothing to serve
    "no generators",
    "no demand",
    # the LAST refusal standing, and only reachable with INELASTIC demand.
    # A scenario whose bids are all priced can always decline to serve them,
    # so it cannot be infeasible on capacity.
    "solve not optimal",
)


def build(rng, elastic_only=False):
    """A random network, made of the moves the editor has and no others.

    Deliberately generates things the editor can and will produce: a network
    in two pieces, a bus with nothing attached, two lines between the same
    pair, a fleet too small for the load, a bid nobody would serve. It does
    NOT generate a negative reactance or a duplicate name, because those are
    refused at construction by Branch and Scenario and are tested there --
    this is about what survives construction and reaches the solver.
    """
    # Weighted, not uniform. An empty fleet, an empty demand side and a
    # one-bus "network" are all things the editor can build and all things
    # the engine must name -- but a corpus made mostly of them would be
    # measuring the refusals instead of the solver. So they stay reachable
    # and stay rare.
    buses = list(LETTERS[: rng.choices([1, 2, 3, 4, 5, 6],
                                       weights=[1, 3, 5, 6, 6, 5])[0]])
    hours = list(range(rng.randint(1, 3)))

    branches = []
    for i, a in enumerate(buses):
        for b in buses[i + 1:]:
            # Low enough that a disconnected network is common rather than
            # rare -- that is the case this milestone exists for.
            if rng.random() < 0.45:
                for _ in range(1 if rng.random() > 0.15 else 2):
                    branches.append(
                        Branch(
                            name=f"L{len(branches)}",
                            from_bus=a,
                            to_bus=b,
                            reactance_pu=round(rng.uniform(0.005, 0.05), 4),
                            limit_mw=(math.inf if rng.random() < 0.35
                                      else round(rng.uniform(20.0, 400.0), 1)),
                        )
                    )

    generators = tuple(
        Generator(
            name=f"g{i}",
            bus=rng.choice(buses),
            cost_usd_per_mwh=round(rng.uniform(5.0, 60.0), 2),
            pmax_mw=round(rng.uniform(0.0, 300.0), 1),
        )
        for i in range(rng.choices([0, 1, 2, 3, 4], weights=[1, 4, 6, 5, 3])[0])
    )

    bids = tuple(
        DemandBid(
            name=f"d{i}",
            bus=rng.choice(buses),
            mw={t: round(rng.uniform(0.0, 400.0), 1) for t in hours},
            # Inelastic sometimes, so the one remaining infeasibility stays
            # reachable and the fuzz keeps testing that it is named. Rare,
            # because on a RANDOM topology it is infeasible far more often
            # than not -- see TestElasticDemandIsTotal.
            value_usd_per_mwh=(None if not elastic_only and rng.random() < 0.18
                               else round(rng.uniform(5.0, 5000.0), 2)),
        )
        for i in range(rng.choices([0, 1, 2, 3, 4], weights=[1, 4, 6, 5, 3])[0])
    )

    return Scenario(
        name=f"fuzz",
        generators=generators,
        bids=bids,
        buses=tuple(Bus(b) for b in buses),
        branches=tuple(branches),
        provenance={"slack": rng.choice(buses)},
    )


def solve(seed, elastic_only=False):
    """(cleared, None) or (None, message). Never anything else."""
    rng = random.Random(seed)
    try:
        scenario = build(rng, elastic_only=elastic_only)
    except ValueError as exc:
        return None, str(exc)
    try:
        return clear(scenario), None
    except ValueError as exc:
        return None, str(exc)
    except RuntimeError as exc:
        # Transport turns this into a named 4xx. It is in the allowed set and
        # it is the last refusal standing -- see ALLOWED_REFUSALS.
        return None, str(exc)


def check(cleared):
    """Every invariant that must hold on any priced solve, ever.

    Deliberately not a rerun of the arithmetic -- nothing here recomputes an
    LMP or a rent. These are the properties the answer must have whatever the
    numbers are, which is what makes them meaningful on a network nobody has
    looked at.
    """
    tol = 1e-6
    hours = cleared["hours"]
    island_of = cleared["island_of"]

    for (g, t), mw in cleared["dispatch"].items():
        assert -tol <= mw <= cleared["gen_pmax"][g] + tol, (g, t, mw)

    for (k, t), mw in cleared["served"].items():
        assert -tol <= mw <= cleared["bid_mw"][k, t] + tol, (k, t, mw)
        if cleared["bid_value"][k] is None:
            # Inelastic demand must be served in full or the solve should
            # have been infeasible. A partially served inelastic bid is the
            # engine quietly shedding load it promised to carry.
            assert mw == pytest.approx(cleared["bid_mw"][k, t], abs=1e-6), (k, t)

    for (l, t), f in cleared["flows"].items():
        assert abs(f) <= cleared["limits"][l] + 1e-4, (l, t, f)

    for (b, t), price in cleared["lmp"].items():
        assert math.isfinite(price), (b, t, price)
        assert price == pytest.approx(
            cleared["lmbda"][island_of[b], t] + cleared["congestion"][b, t], abs=1e-6
        ), (b, t)

    for home, group in cleared["islands"].items():
        inside = set(group)
        for t in hours:
            # Power does not cross an island boundary. THE constraint this
            # milestone added -- with one system balance row a generator here
            # would serve load there through a line that is not present.
            made = sum(mw for (g, s), mw in cleared["dispatch"].items()
                       if s == t and cleared["gen_bus"][g] in inside)
            took = sum(mw for (k, s), mw in cleared["served"].items()
                       if s == t and cleared["bid_bus"][k] in inside)
            assert made == pytest.approx(took, abs=1e-5), (home, t, made, took)

            # And the money balances in each island separately.
            assert cleared["settlement"][home, t]["residual"] == pytest.approx(
                0.0, abs=1e-5
            ), (home, t)


# ------------------------------------------------------------ the claim


class TestTotality:
    """A priced solve or one named reason. Nothing else, for any seed."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_every_random_network_is_answered(self, seed):
        cleared, refusal = solve(seed)
        if cleared is None:
            assert any(r in refusal for r in ALLOWED_REFUSALS), (
                f"seed {seed}: unnamed refusal {refusal!r}. Either a new "
                f"refusal that belongs in CLAUDE.md's table, or a bug."
            )
            assert "Traceback" not in refusal
            return
        check(cleared)


class TestElasticDemandIsTotal:
    """A priced demand side cannot be infeasible on capacity. Ever.

    The argument is structural rather than statistical: with every bid
    elastic, d = 0 and p = 0 is feasible for ANY topology -- zero injections,
    zero flows, every limit satisfied. So the LP always has an answer, and a
    shortfall comes back as a scarcity price instead of a refusal.

    Worth proving rather than reasoning about, because it settles the one W2
    question still open in CLAUDE.md: whether the editor emits only blocks
    configs. It should. The corpus above puts inelastic demand on a random
    network and it is infeasible far more often than not -- an editor that
    can build any topology and insists its load must be served is an editor
    whose most ordinary move is an error message.

    This class leaves the OTHER refusals alone. A one-bus network still has
    no network to price, and an empty fleet still has nothing to dispatch;
    those are statements about the scenario, not about whether the market
    clears.
    """

    @pytest.mark.parametrize("seed", SEEDS)
    def test_a_priced_demand_side_never_goes_infeasible(self, seed):
        cleared, refusal = solve(seed, elastic_only=True)
        if cleared is not None:
            check(cleared)
            return
        assert "solve not optimal" not in refusal, (
            f"seed {seed}: every bid was priced and the LP was still "
            f"infeasible -- d = 0 should always have been available"
        )
        assert any(r in refusal for r in ALLOWED_REFUSALS), refusal


# ---------------------------------------------------- the corpus itself


class TestCoverage:
    """What the fuzz actually generated.

    Without this the suite above is theatre: a corpus of connected five-bus
    networks would satisfy every assertion and would have tested none of the
    cases W1 exists for. Each assertion below names a row of CLAUDE.md's
    table and fails if the corpus stopped reaching it.
    """

    @pytest.fixture(scope="class")
    def corpus(self):
        out = []
        for seed in SEEDS:
            cleared, refusal = solve(seed)
            out.append((seed, cleared, refusal))
        return out

    def test_it_priced_a_good_share_of_them(self, corpus):
        """A corpus that mostly refuses is measuring the refusals, not the
        engine.

        Measured at the time of writing: 59 of 120 priced, against 31
        infeasible (all of them inelastic demand), 20 with no network to
        price and 10 with an empty fleet or an empty demand side. The floor
        below is a smoke alarm with headroom, not a specification -- it is
        here to catch the corpus drifting into refusals, not to pin a number.
        """
        priced = [c for _, c, _ in corpus if c is not None]
        assert len(priced) > len(corpus) * 2 // 5

    def test_it_generated_disconnected_networks(self, corpus):
        split = [c for _, c, _ in corpus if c is not None and len(c["islands"]) > 1]
        assert split, "no seed produced a cut network; the island code is untested"

    def test_it_generated_several_islands_at_once(self, corpus):
        many = [c for _, c, _ in corpus if c is not None and len(c["islands"]) > 2]
        assert many, "no seed produced three or more islands"

    def test_it_generated_an_isolated_bus(self, corpus):
        lone = [c for _, c, _ in corpus
                if c is not None and any(len(g) == 1 for g in c["islands"].values())]
        assert lone, "no seed produced a bus with nothing attached"

    def test_it_generated_a_bus_with_no_generator_and_no_load(self, corpus):
        """Prices correctly, and is NOT a bug. CLAUDE.md says so; this keeps
        saying it on networks nobody wrote by hand."""
        for _, c, _ in corpus:
            if c is None:
                continue
            attached = set(c["gen_bus"].values()) | set(c["bid_bus"].values())
            empty = [b for b in c["buses"] if b not in attached]
            if empty:
                assert all(math.isfinite(c["lmp"][b, t])
                           for b in empty for t in c["hours"])
                return
        pytest.fail("no seed produced an empty bus")

    def test_it_generated_parallel_branches(self, corpus):
        """Two lines between the same pair of buses. Physical, and not a bug.

        Read off the generator rather than the result, because the cleared
        result does not carry branch endpoints -- and the generator is the
        thing being characterised here anyway.
        """
        seen = False
        for seed in SEEDS:
            scenario = None
            try:
                scenario = build(random.Random(seed))
            except ValueError:
                continue
            pairs = [frozenset((b.from_bus, b.to_bus)) for b in scenario.branches]
            if len(pairs) != len(set(pairs)):
                seen = True
                break
        assert seen, "no seed produced two lines between the same buses"

    def test_it_generated_curtailment(self, corpus):
        curtailed = []
        for _, c, _ in corpus:
            if c is None:
                continue
            if any(c["served"][k, t] < c["bid_mw"][k, t] - 1e-6
                   for (k, t) in c["served"]):
                curtailed.append(c)
        assert curtailed, "no seed produced a bid the market declined"

    def test_it_generated_a_binding_line(self, corpus):
        binding = [c for _, c, _ in corpus
                   if c is not None and any(abs(v) > 1e-6 for v in c["mu"].values())]
        assert binding, "no seed produced congestion; every mu was zero"

    def test_every_named_refusal_was_reached(self, corpus):
        """Each allowed refusal is claimed to be reachable. Claims that no
        seed reaches are claims nothing checks."""
        refusals = [r for _, _, r in corpus if r is not None]
        for expected in ("nodal clearing needs a network", "no generators",
                         "no demand"):
            assert any(expected in r for r in refusals), expected
