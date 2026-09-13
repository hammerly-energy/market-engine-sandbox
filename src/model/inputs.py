"""Scenario and its parts: Generator, Bus, Branch, DemandBid.

The boundary between ingest and model. Nothing in src/model/ may call a data
source; it reads a Scenario and nothing else.

That rule is what this module exists to enforce. A Scenario is inert: frozen
dataclasses, plain floats, a UTC-timestamped load, and a provenance dict that
records where the numbers came from without being able to go get more. There
is no fetch, no path, no API key, and no pandas dependency below this line --
the solver cannot reach a data source even by accident.

At M2 the network is empty. Bus and Branch are declared because the shape of
the object should not change when M3 fills them in, and because `buses = one`
is a claim worth being able to see rather than an omission.

              ingest/                     |            model/
    EIA-930 --> parse --> validate --> Scenario --> dispatch --> duals
    a config ->  ...  -->   ...    -->    ^
                                          |
                        the boundary. one direction only.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Sequence, Tuple


@dataclass(frozen=True)
class Bus:
    """A node. At M2 there is exactly one and it carries no information."""
    name: str


@dataclass(frozen=True)
class Branch:
    """A transmission line with a thermal limit.

    reactance_pu is strictly positive, and that is not a style rule. The DC
    model inverts it -- b = 1/x -- and then builds every matrix in
    src/network/ out of the result:

        x > 0    b > 0     B_bus is positive semidefinite. One zero
                           eigenvalue, the angle reference, which ptdf()
                           removes on purpose. This is the physical case.

        x = 0    b = inf   ZeroDivisionError inside b_branch().

        x < 0    b < 0     B_bus is INDEFINITE. It still inverts, the LP
                           still solves, and it returns prices that look
                           entirely plausible and mean nothing. A negative
                           reactance is a line that carries power uphill.

    The third case is why this check exists here rather than being left to
    the linear algebra. A bad reactance does not raise anywhere downstream;
    it produces a confident wrong answer, which is the one failure mode no
    test catches and no user notices.
    """
    name: str
    from_bus: str
    to_bus: str
    reactance_pu: float
    limit_mw: float

    def __post_init__(self):
        if self.from_bus == self.to_bus:
            # Incidence would put +1 and -1 in the same column, giving an
            # all-zero row: a line whose flow is identically zero and which
            # contributes nothing to B_bus. Harmless arithmetic, meaningless
            # network.
            raise ValueError(
                f"{self.name}: from_bus and to_bus are both {self.from_bus!r}"
            )
        if not self.reactance_pu > 0:
            raise ValueError(
                f"{self.name}: reactance_pu must be > 0, got {self.reactance_pu}"
            )
        if not self.limit_mw > 0:
            # inf passes: an unlimited line is a modelling choice this repo
            # uses deliberately, and inf > 0 is True. Zero does not, because a
            # line that can carry nothing is a line that should be deleted --
            # keeping it makes every solve infeasible for a reason the user
            # cannot see on screen.
            raise ValueError(
                f"{self.name}: limit_mw must be > 0, got {self.limit_mw}"
            )


@dataclass(frozen=True)
class Generator:
    """An offer: a price and a quantity, located at a bus.

    cost_usd_per_mwh is a single marginal cost, not yet a curve. It becomes
    fuel_price * heat_rate + VOM at M5 and a real ERCOT offer curve later.
    pmin_mw is carried but not enforced -- an LP has no way to honour it
    (trap 4), which is the whole reason M6 exists.
    """
    name: str
    bus: str
    cost_usd_per_mwh: float
    pmax_mw: float
    pmin_mw: float = 0.0

    def __post_init__(self):
        if self.pmax_mw < 0:
            raise ValueError(f"{self.name}: negative pmax_mw {self.pmax_mw}")
        if not 0 <= self.pmin_mw <= self.pmax_mw:
            raise ValueError(
                f"{self.name}: pmin_mw {self.pmin_mw} outside [0, {self.pmax_mw}]"
            )


@dataclass(frozen=True)
class DemandBid:
    """Demand at one bus, named, keyed by hour, and optionally priced.

    Deliberately the mirror image of Generator -- (name, bus, price, quantity)
    against (name, bus, price, quantity) -- because economically it IS one. A
    consumer willing to pay $300 and a generator offering at $300 are the same
    object pointed in opposite directions, and the LP does not care which side
    of the balance a variable sits on.

        Generator   name  bus  cost_usd_per_mwh   pmax_mw
        DemandBid   name  bus  value_usd_per_mwh  mw[t]

    THE NAME IS THE POINT. An anonymous block indexed (bus, k) cannot later
    carry an owner or a constraint that spans hours without renumbering every
    config and every test. A named one can: `datacenter_dr` at bus B valued at
    $300/MWh is a demand response resource already, and a duration limit at M9
    attaches to that name. Naming costs nothing now and is the only thing that
    makes the demand side extensible later.

    mw maps an hour label to MW. The label's TYPE belongs to the source: an
    ISO-8601 UTC string for real data (M2), the literal "static" for a
    textbook snapshot (M3), an integer 0..23 for a synthetic day (M4). A
    string, not a pandas Timestamp, so the model layer needs no pandas and a
    Scenario stays trivially serializable into a run directory.

    value_usd_per_mwh is what one MW is worth to this consumer, and its
    absence is a claim rather than a gap:

        None    INELASTIC. Must be served. Demand stays a constant on the
                right-hand side of the energy balance, which is exactly the
                M0-M4 formulation, unchanged. Every existing config takes this
                branch and every existing number is untouched.

        float   ELASTIC. The bid becomes a VARIABLE bounded 0..mw[t] with a
                benefit term in the objective, and the market may decline to
                serve it when the price exceeds what it is worth. Firm load is
                this with the value set to the offer cap, so "load cannot be
                served" stops being an infeasibility and becomes a price.

    The engine does not yet read the second branch -- that formulation is
    W1's, and dispatch.py is where it lands. This class carries the data so
    that the ingest path, the config schema and the tests can exist and pass
    BEFORE the LP changes, rather than all five things having to land at once.
    """
    name: str
    bus: str
    mw: Dict[str, float]
    value_usd_per_mwh: Optional[float] = None

    def __post_init__(self):
        if self.value_usd_per_mwh is not None and self.value_usd_per_mwh < 0:
            # A negative valuation is a consumer who must be PAID to take
            # power. That is a real thing (a must-run industrial process, a
            # curtailment payment) but it is not what a typo means, and the
            # LP would happily serve it to collect the benefit.
            raise ValueError(
                f"{self.name}: value_usd_per_mwh must be >= 0, got "
                f"{self.value_usd_per_mwh}"
            )
        if not self.mw:
            raise ValueError(f"{self.name}: no hours")
        for t, mw in self.mw.items():
            if mw < 0:
                raise ValueError(f"{self.name}: negative demand {mw} at hour {t!r}")

    @property
    def elastic(self) -> bool:
        """True if the market may decline to serve this bid."""
        return self.value_usd_per_mwh is not None


@dataclass(frozen=True)
class Scenario:
    """Everything one solve needs, and nothing about where it came from.

    provenance is the exception that proves the rule: it is a record FOR the
    run directory, opaque to the solver, and it must never contain anything
    callable.
    """
    name: str
    generators: Tuple[Generator, ...]
    bids: Tuple[DemandBid, ...]
    buses: Tuple[Bus, ...] = ()
    branches: Tuple[Branch, ...] = ()
    provenance: Dict = field(default_factory=dict)

    def __post_init__(self):
        # Bus names are the column order of every matrix in src/network/ and
        # the keys of every price. A repeat gives B_bus two identical rows,
        # which is singular for a reason that has nothing to do with the angle
        # reference ptdf() expects to remove -- so it surfaces as "Singular
        # matrix" from inside numpy, indistinguishable from a network that was
        # simply cut in half.
        bus_names = [b.name for b in self.buses]
        if len(bus_names) != len(set(bus_names)):
            dupes = sorted({n for n in bus_names if bus_names.count(n) > 1})
            raise ValueError(f"duplicate bus names: {dupes}")

        # A Branch validates itself, but it cannot see the bus list, so this is
        # the only place an endpoint typo can be caught. Left alone it becomes
        # a bare KeyError two modules away in incidence().
        branch_names = [br.name for br in self.branches]
        if len(branch_names) != len(set(branch_names)):
            dupes = sorted({n for n in branch_names if branch_names.count(n) > 1})
            raise ValueError(f"duplicate branch names: {dupes}")
        known = set(bus_names)
        for br in self.branches:
            for end, bus in (("from_bus", br.from_bus), ("to_bus", br.to_bus)):
                if bus not in known:
                    raise ValueError(
                        f"branch {br.name}: {end} {bus!r} is not a declared bus "
                        f"{sorted(known)}"
                    )

        names = [g.name for g in self.generators]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate generator names in {names}")
        if not self.generators:
            raise ValueError(f"{self.name}: no generators")
        bid_names = [b.name for b in self.bids]
        if len(bid_names) != len(set(bid_names)):
            dupes = sorted({n for n in bid_names if bid_names.count(n) > 1})
            raise ValueError(f"duplicate demand bid names: {dupes}")
        if not self.bids:
            raise ValueError(f"{self.name}: no demand")
        spans = {tuple(sorted(b.mw)) for b in self.bids}
        if len(spans) > 1:
            raise ValueError("demand bids disagree on the hour index")

    # -- views the solver consumes. plain dicts, no pandas, no I/O. --

    @property
    def hours(self) -> Sequence[str]:
        """The horizon, as sorted ISO-8601 UTC strings."""
        return sorted(self.bids[0].mw)

    def cost(self) -> Dict[str, float]:
        """{gen: $/MWh}, the c argument to solve_dispatch_day."""
        return {g.name: g.cost_usd_per_mwh for g in self.generators}

    def pmax(self) -> Dict[str, float]:
        """{gen: MW}, the Pmax argument to solve_dispatch_day."""
        return {g.name: g.pmax_mw for g in self.generators}

    def demand(self) -> Dict[str, float]:
        """{hour: MW}, summed over buses. The D argument to solve_dispatch_day.

        Single-bus at M2, so this sum is over one term. At M3 the solver stops
        wanting a system total and starts wanting demand per bus, and this
        method gets a sibling rather than a rewrite.
        """
        return {
            t: sum(b.mw[t] for b in self.bids)
            for t in self.hours
        }

    @property
    def total_capacity_mw(self) -> float:
        return sum(g.pmax_mw for g in self.generators)

    @property
    def peak_load_mw(self) -> float:
        d = self.demand()
        return max(d.values())

    def demand_by_bus(self) -> Dict[str, Dict[str, float]]:
        """{bus: {hour: MW}}. Sibling to demand(), not a replacement.

        Every bus gets an entry, including the ones carrying no load. The
        network solver needs D[i, t] for every i to form an injection, and a
        bus that is simply absent from the mapping is a KeyError rather than
        a zero.

        Loads are summed, not assigned, because nothing stops two Load objects
        sitting at the same bus -- and a dict comprehension would silently
        keep only the last of them.
        """
        out = {b.name: {t: 0.0 for t in self.hours} for b in self.buses}
        for bid in self.bids:
            if bid.bus not in out:
                raise ValueError(f"demand bid at unknown bus {bid.bus!r}")
            for t, mw in bid.mw.items():
                out[bid.bus][t] += mw
        return out

    def inelastic_by_bus(self) -> Dict[str, Dict[str, float]]:
        """{bus: {hour: MW}}, counting ONLY the bids that must be served.

        The sibling demand_by_bus() sums every bid and answers "how much was
        asked for"; this answers "how much is not up for negotiation", which
        is the constant the energy balance carries. With no elastic bids the
        two are identical, which is why M0-M4 are untouched.

        Every bus gets an entry, including ones carrying no load at all: the
        network solver needs a number per bus to form an injection, and an
        absent bus is a KeyError rather than a zero.
        """
        out = {b.name: {t: 0.0 for t in self.hours} for b in self.buses}
        for bid in self.bids:
            if bid.elastic:
                continue
            if bid.bus not in out:
                raise ValueError(f"demand bid at unknown bus {bid.bus!r}")
            for t, mw in bid.mw.items():
                out[bid.bus][t] += mw
        return out

    # -- views a demand-side formulation will want. data only, no LP. --

    def bid_value(self) -> Dict[str, Optional[float]]:
        """{bid: $/MWh or None}. None is inelastic -- see DemandBid."""
        return {b.name: b.value_usd_per_mwh for b in self.bids}

    def bid_mw(self) -> Dict[Tuple[str, str], float]:
        """{(bid, hour): MW}. The upper bound on an elastic bid's variable."""
        return {(b.name, t): mw for b in self.bids for t, mw in b.mw.items()}

    def bid_bus(self) -> Dict[str, str]:
        """{bid: bus}. The demand-side twin of gen_bus."""
        return {b.name: b.bus for b in self.bids}

    @property
    def elastic_bids(self) -> Tuple[DemandBid, ...]:
        """The bids the market may decline to serve. Empty through M4."""
        return tuple(b for b in self.bids if b.elastic)
