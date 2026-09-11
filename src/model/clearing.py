"""One call from a Scenario to a cleared, priced, settled market.

Everything here already existed, scattered across a __main__ block and a test
helper: build the PTDF, solve the LP, assemble the prices, check the identity.
Nothing new is formulated. What is new is that the whole pipeline has ONE name,
so a caller that is not a figure -- a parameter sweep, an HTTP handler, a
notebook -- can run a market without reassembling the sequence by hand and
getting one step subtly wrong.

    Scenario --> ptdf() --> solve_dispatch_network_day() --> lmps() --> settle()
       |           |                    |                      |          |
     buses      PTDF[l,i]           p, lambda, mu           LMP[i]    residual
     branches                                                          == 0

The slack is an ARGUMENT, not a Scenario field. It is a choice this layer
makes, and per CLAUDE.md trap 2 nothing physical depends on it: changing it
shifts every LMP by a constant and moves no dispatch, no flow, and no price
DIFFERENCE. It defaults to whatever the config recorded so that the common
case needs no second argument.
"""

import numpy as np

from src.model.dispatch import solve_dispatch_network_day
from src.model.pricing import (
    congestion,
    congestion_prices,
    generator_status,
    headroom,
    lmps,
    reduced_costs,
)
from src.network.ptdf import ptdf
from src.settle.settlement import settle


def clear(scenario, slack=None, limits=None):
    """Clear, price, and settle every hour of a Scenario.

    Args:
        scenario: a Scenario carrying buses and branches. Single-bus scenarios
                  are rejected -- they have no network, and M0's solve_dispatch
                  is the right call for them.
        slack:    bus name. Defaults to scenario.provenance["slack"].
        limits:   {line: MW} overriding the branch ratings. The lever a sweep
                  or a UI slider pulls: pass {"DE": 240.0} to re-solve one
                  network at a different rating without rebuilding a Scenario.
                  Lines omitted keep their declared limit; np.inf is allowed
                  and means unlimited.

    Returns:
        A dict keyed by hour under "hours", with everything a caller needs to
        draw or serve the result. Dispatch, flows, mu and lmp are keyed by
        (name, hour) exactly as the solver returns them -- not re-nested --
        because a caller that wants one snapshot indexes once, and a caller
        that wants the day iterates, and neither has to undo a shape the other
        preferred.

        Three fields exist for a drawing caller rather than for the solve, and
        are derived, not new arithmetic: "congestion" is the half of the LMP
        that lmps() used to discard, "gen_cost"/"gen_pmax" are the fleet read
        straight off the Scenario so a merit-order stack can be drawn without
        the caller holding the config too, and "gen_status"/"headroom"/
        "reduced_cost" are where each unit sits and what that is worth. They
        live here because the alternative is a second, untested implementation
        of the same arithmetic in the browser.

    Raises:
        ValueError on a scenario this cannot price; RuntimeError from the
        solver if the LP is infeasible or unbounded.
    """
    buses = [b.name for b in scenario.buses]
    branches = list(scenario.branches)
    if len(buses) < 2 or not branches:
        raise ValueError(
            f"{scenario.name}: nodal clearing needs a network; got "
            f"{len(buses)} bus(es) and {len(branches)} branch(es)"
        )

    if slack is None:
        slack = scenario.provenance.get("slack")
    if slack is None:
        raise ValueError("no slack bus: pass slack= or record network.slack")
    if slack not in buses:
        raise ValueError(f"slack {slack!r} is not a bus in {buses}")

    lines = [br.name for br in branches]
    # Row order is branches, column order is buses, and both are fixed HERE and
    # passed down. Every consumer of the PTDF re-derives its index from these
    # two lists rather than from its own ordering assumption.
    PTDF = ptdf(buses, branches, slack)

    Fmax = {br.name: br.limit_mw for br in branches}
    if limits:
        unknown = set(limits) - set(Fmax)
        if unknown:
            raise ValueError(f"limit override for unknown line(s) {sorted(unknown)}")
        Fmax.update({l: float(v) for l, v in limits.items()})

    gen_bus = {g.name: g.bus for g in scenario.generators}

    # Demand splits in two, and the split is the bid's own declaration rather
    # than a setting here: a bid with a value is one the market may decline,
    # a bid without one is a constant on the balance row. With no elastic
    # bids -- every scenario through M4 -- D is demand_by_bus() exactly and
    # the solver builds the M4 model.
    D = scenario.inelastic_by_bus()
    elastic = scenario.elastic_bids
    bid_bus = {b.name: b.bus for b in elastic}
    bid_value = {b.name: b.value_usd_per_mwh for b in elastic}
    bid_mw = {(b.name, t): mw for b in elastic for t, mw in b.mw.items()}

    res = solve_dispatch_network_day(
        c=scenario.cost(),
        Pmax=scenario.pmax(),
        D=D,
        gen_bus=gen_bus,
        buses=buses,
        PTDF=PTDF,
        Fmax=Fmax,
        bid_value=bid_value,
        bid_mw=bid_mw,
        bid_bus=bid_bus,
    )

    # What each bid actually got. Inelastic bids got what they asked for by
    # definition; elastic ones got what the market decided they were worth.
    # Reported for BOTH so a caller never has to know which kind it is
    # holding -- the distinction is the engine's, not the reader's.
    served = {(b.name, t): mw for b in scenario.bids if not b.elastic
              for t, mw in b.mw.items()}
    served.update(res["d"])
    served_by_bus = {i: dict(D[i]) for i in buses}
    for (k, t), mw in res["d"].items():
        served_by_bus[bid_bus[k]][t] += mw

    mu = congestion_prices(res)
    lmp = lmps(res, buses, lines, PTDF)
    cong = congestion(res, buses, lines, PTDF)

    cost, Pmax = scenario.cost(), scenario.pmax()
    status = generator_status(res, Pmax)
    slack_mw = headroom(res, Pmax)
    reduced = reduced_costs(lmp, cost, gen_bus, scenario.hours)

    # Settlement is per hour because the identity is per hour. Summing the day
    # first would let a positive residual in one hour cancel a negative one in
    # another and report a clean zero over a broken solve.
    settlement = {}
    for t in scenario.hours:
        gen_mw = {b: 0.0 for b in buses}
        for g, bus in gen_bus.items():
            gen_mw[bus] += res["p"][g, t]
        settlement[t] = settle(
            lmp={b: lmp[b, t] for b in buses},
            # SERVED, not declared. Load pays for what it took. Billing
            # declared demand while the injection carries served demand puts
            # the difference straight into the residual, where it reads like
            # a PTDF sign error and is not one.
            load_mw={b: served_by_bus[b][t] for b in buses},
            gen_mw=gen_mw,
            mu={l: mu[l, t] for l in lines},
            flows={l: res["f"][l, t] for l in lines},
        )

    return {
        "buses": buses,
        "lines": lines,
        "slack": slack,
        "hours": list(scenario.hours),
        "limits": Fmax,
        "gen_bus": gen_bus,
        "dispatch": res["p"],      # {(gen, hour): MW}
        "flows": res["f"],         # {(line, hour): MW}
        "mu": mu,                  # {(line, hour): $/MWh}
        "lmp": lmp,                # {(bus, hour): $/MWh}
        "congestion": cong,        # {(bus, hour): $/MWh}, lmp - lmbda
        "lmbda": res["lmbda"],     # {hour: $/MWh}
        "gen_cost": cost,          # {gen: $/MWh}
        "gen_pmax": Pmax,          # {gen: MW}
        # Where each unit sits, what its headroom is, and what one more MW is
        # worth to it. Status is a dispatch fact; reduced_cost is the money.
        # Neither says "this unit sets the price" on its own, because under
        # congestion no single unit does -- see pricing.generator_status.
        "gen_status": status,      # {(gen, hour): "off"|"interior"|"at_max"}
        "headroom": slack_mw,      # {(gen, hour): MW}
        "reduced_cost": reduced,   # {(gen, hour): $/MWh}
        "cost": res["cost"],       # $ production cost over the horizon
        "benefit": res["benefit"],     # $ consumer benefit; 0 with no bids
        "served": served,          # {(bid, hour): MW} actually consumed
        "bid_bus": {b.name: b.bus for b in scenario.bids},
        "bid_value": scenario.bid_value(),   # {bid: $/MWh or None}
        "bid_mw": scenario.bid_mw(),         # {(bid, hour): MW} asked for
        "settlement": settlement,  # {hour: {...}}
        "PTDF": PTDF,
    }


def binding_lines(cleared, hour, tol=1e-9):
    """Line names whose flow limit is holding the dispatch back, at one hour.

    A line is binding when its dual is non-zero, not when its flow is near its
    rating. Those usually coincide, but the dual is the one that answers the
    question a market asks -- would one more MW of this line change the cost --
    and it is the number the price is assembled from.
    """
    return {l for l in cleared["lines"] if abs(cleared["mu"][l, hour]) > tol}
