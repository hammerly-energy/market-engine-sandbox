"""One call from a Scenario to a cleared, priced, settled market.

Everything here already existed, scattered across a __main__ block and a test
helper: build the PTDF, solve the LP, assemble the prices, check the identity.
Nothing new is formulated. What is new is that the whole pipeline has one name,
so a caller that is not a figure -- a parameter sweep, an HTTP handler, a
notebook -- can run a market without reassembling the sequence by hand and
getting one step subtly wrong.

    Scenario --> ptdf() --> solve_dispatch_network_day() --> lmps() --> settle()
       |           |                    |                      |          |
     buses      PTDF[l,i]           p, lambda, mu           LMP[i]    residual
     branches                                                          == 0

The slack is an argument, not a Scenario field. It is a choice this layer
makes, and per CLAUDE.md trap 2 nothing physical depends on it: changing it
moves lambda and moves no LMP at all, no dispatch, no flow and no settlement
figure. It defaults to whatever the config recorded so that the common case
needs no second argument.
"""

import numpy as np

from src.model.dispatch import solve_dispatch_network_day
from src.model.pricing import (
    congestion,
    congestion_prices,
    generator_status,
    headroom,
    line_loading,
    lmps,
    price_uniqueness,
    reduced_costs,
)
from src.network.ptdf import ptdf_blocks
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

        Four fields exist for a drawing caller rather than for the solve, and
        are derived, not new arithmetic: "congestion" is the half of the LMP
        that lmps() used to discard, "gen_cost"/"gen_pmax" are the fleet read
        straight off the Scenario so a merit-order stack can be drawn without
        the caller holding the config too, "gen_status"/"headroom"/
        "reduced_cost" are where each unit sits and what that is worth, and
        "loading" is a flow against its own rating. They live here because the
        alternative is a second, untested implementation of the same
        arithmetic in the browser.

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

    # A slack that is no longer a bus is chosen when it came from the config
    # and refused when the caller named it. The two are different claims:
    #
    #     slack=          an assertion by this caller, about this call. If it
    #                     names a bus that is not there, the caller is wrong
    #                     and should hear about it. A typo silently answering
    #                     about a different bus is how a sweep reports 24
    #                     hours of the wrong lambda and nobody notices.
    #
    #     provenance      a record, written when the config was parsed and
    #                     possibly stale by now. The editor deletes a bus and
    #                     the recorded slack names something gone. Refusing
    #                     there would make deleting the slack the one edit
    #                     that breaks the site -- and it would refuse for no
    #                     physical reason, because the slack is an accounting
    #                     origin (trap 2). Any bus works, no LMP, dispatch,
    #                     flow or settlement figure depends on which, and only
    #                     the level of lambda moves.
    #
    # The fallback is the first bus in the caller's order, so the same config
    # gives the same answer twice and the choice is derivable without running
    # anything. It does not raise; it is not unreported. The chosen slack is
    # returned under "slack" and names its island in "islands" and "lmbda", so
    # a caller whose recorded slack is gone can see which one it got. A number
    # the UI displays may not be picked privately -- the same rule
    # island_slacks follows.
    if slack is not None:
        if slack not in buses:
            raise ValueError(f"slack {slack!r} is not a bus in {buses}")
    else:
        slack = scenario.provenance.get("slack")
        if slack not in buses:
            slack = buses[0]

    lines = [br.name for br in branches]
    # Row order is branches, column order is buses, and both are fixed here and
    # passed down. Every consumer of the PTDF re-derives its index from these
    # two lists rather than from its own ordering assumption.
    #
    # ptdf_blocks, not ptdf: a cut network is two markets, not an error. The
    # matrix comes back block diagonal and islands says which bus belongs to
    # which market, keyed by that market's slack. For a connected network
    # there is exactly one entry and the matrix is ptdf()'s, unchanged.
    PTDF, islands = ptdf_blocks(buses, branches, slack)
    island_of = {b: home for home, group in islands.items() for b in group}

    Fmax = {br.name: br.limit_mw for br in branches}
    if limits:
        unknown = set(limits) - set(Fmax)
        if unknown:
            raise ValueError(f"limit override for unknown line(s) {sorted(unknown)}")
        # The override is a rating and is held to the rating rule, which is
        # Branch.__post_init__'s: strictly positive, inf allowed. It has to be
        # restated here because the override never passes through Branch --
        # it is an argument to clear(), not an edit to the Scenario -- so
        # until W3.8 the one field the UI hands the engine most often was the
        # one field nothing checked. Measured on w1.yaml at hour 18:
        #
        #     0 MW    solves. mu[DE] = $13,527.99, D prices at the $5000 cap
        #             and E at -$1499.55, while f = 7.1e-15 and line_loading
        #             reports 0.0 because it divides by a zero rating. So the
        #             panel prints an idle line next to the largest dual in
        #             the repo.
        #     -1 MW   RuntimeError: solve not optimal: infeasible.
        #     nan     ValueError from Pyomo naming mu_up[DE,0], a sentence
        #             about a constraint index rather than about a rating.
        #
        # `not (v > 0)` catches all three, nan included, and inf passes.
        checked = {}
        for l, v in limits.items():
            v = float(v)
            if not v > 0:
                raise ValueError(
                    f"limit override for {l}: limit_mw must be > 0, got {v}"
                )
            checked[l] = v
        Fmax.update(checked)

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
        islands=islands,
        bid_value=bid_value,
        bid_mw=bid_mw,
        bid_bus=bid_bus,
    )

    # What each bid actually got. Inelastic bids got what they asked for by
    # definition; elastic ones got what the market decided they were worth.
    # Reported for both so a caller never has to know which kind it is
    # holding -- the distinction is the engine's, not the reader's.
    served = {(b.name, t): mw for b in scenario.bids if not b.elastic
              for t, mw in b.mw.items()}
    served.update(res["d"])
    served_by_bus = {i: dict(D[i]) for i in buses}
    for (k, t), mw in res["d"].items():
        served_by_bus[bid_bus[k]][t] += mw

    # Which lines belong to which market. Every branch has both ends in one
    # component, so from_bus decides it.
    island_lines = {home: [br.name for br in branches if br.from_bus in set(group)]
                    for home, group in islands.items()}

    mu = congestion_prices(res)
    lmp = lmps(res, buses, lines, PTDF, island_of)
    cong = congestion(res, buses, lines, PTDF)

    cost, Pmax = scenario.cost(), scenario.pmax()
    status = generator_status(res, Pmax)
    slack_mw = headroom(res, Pmax)
    loading = line_loading(res, Fmax)
    reduced = reduced_costs(lmp, cost, gen_bus, scenario.hours)

    # Whether this optimum pins one price and one dispatch, per island per
    # hour. A count over fields already computed above, not a second solve.
    uniqueness = price_uniqueness(
        gen_status=status,
        gen_bus=gen_bus,
        served=served,
        bid_mw=scenario.bid_mw(),
        bid_value=scenario.bid_value(),
        bid_bus={b.name: b.bus for b in scenario.bids},
        mu=mu,
        flows=res["f"],
        Fmax=Fmax,
        lmp=lmp,
        reduced_cost=reduced,
        gen_pmax=Pmax,
        islands=islands,
        island_lines=island_lines,
        hours=scenario.hours,
    )

    # Settlement is per island and per hour, because the identity is per
    # island per hour. Summing the day would let a positive residual in one
    # hour cancel a negative one in another; summing the islands would do the
    # identical thing one dimension over, and a cut network is exactly when
    # the two halves are most likely to be wrong in opposite directions.
    settlement = {}
    for home, group in islands.items():
        for t in scenario.hours:
            gen_mw = {b: 0.0 for b in group}
            for g, bus in gen_bus.items():
                if bus in gen_mw:
                    gen_mw[bus] += res["p"][g, t]
            settlement[home, t] = settle(
                lmp={b: lmp[b, t] for b in group},
                # Served, not declared. Load pays for what it took. Billing
                # declared demand while the injection carries served demand
                # puts the difference straight into the residual, where it
                # reads like a PTDF sign error and is not one.
                load_mw={b: served_by_bus[b][t] for b in group},
                gen_mw=gen_mw,
                # Only this island's lines. A line in the other island has its
                # own rent and belongs in its own ledger.
                mu={l: mu[l, t] for l in island_lines[home]},
                flows={l: res["f"][l, t] for l in island_lines[home]},
            )

    return {
        "buses": buses,
        "lines": lines,
        "slack": slack,
        # {slack: [buses]}. One entry for a connected network; more once a cut
        # has split it, each entry a market with its own lambda and its own
        # settlement. Named by the slack because lambda IS the LMP there.
        "islands": islands,
        "island_of": island_of,          # {bus: island}
        "island_lines": island_lines,    # {island: [line]}
        "hours": list(scenario.hours),
        "limits": Fmax,
        "gen_bus": gen_bus,
        "dispatch": res["p"],      # {(gen, hour): MW}
        "flows": res["f"],         # {(line, hour): MW}
        "mu": mu,                  # {(line, hour): $/MWh}
        # f / limit, signed, on [-1, 1]. Direction and loading in one number,
        # which is what a diverging ramp is drawn from. An unrated line is
        # f / inf = 0. Derived, for the same reason headroom is.
        "loading": loading,        # {(line, hour): fraction of rating}
        "lmp": lmp,                # {(bus, hour): $/MWh}
        "congestion": cong,        # {(bus, hour): $/MWh}, lmp - lmbda
        "lmbda": res["lmbda"],     # {(island, hour): $/MWh}
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
        # {(island, hour): {basic, rows, verdict}}. "unique", or which half
        # of the answer is not: "price_is_an_interval" when a row has no
        # variable free to set its dual, "dispatch_is_not_unique" when spare
        # variables sit at zero reduced cost. Two different sentences, never
        # one degenerate bool -- see pricing.price_uniqueness.
        "uniqueness": uniqueness,
        "settlement": settlement,  # {(island, hour): {...}}
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
