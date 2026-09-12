"""Assemble LMPs from dispatch duals.

    LMP[i] = lambda + sum_over_lines( PTDF[l, i] * mu[l] )  [+ loss term]

Sign convention follows how the flow constraint was written. Verify against a
case with a published answer."""

def congestion_prices(res):
    """Price of a line's flow capacity constraint. "$XX.XX/MWh is what a 1 MW higher capacity line would be worth."
    {(line, t): $/MWh}. One signed number per line, from two raw duals."""
    # mu = mu_up - mu_dn
    return {
        (l, t): res["mu_up"][l, t] - res["mu_dn"][l, t]
        for (l, t) in res["mu_up"]
    }

def _hours(res):
    """The horizon, from lmbda's (island, hour) keys.

    lmbda is keyed by island as well as hour, so the hours are one level in.
    Taken as a set and not sorted: these are dict keys, and the order of a
    comprehension over them never reaches a caller.
    """
    return {t for _, t in res["lmbda"]}


def congestion(res, buses, lines, PTDF):
    """The congestion component of the LMP, alone. {(bus, t): $/MWh}.

        congestion[i, t] = sum_over_lines( PTDF[l, i] * mu[l, t] )

    lmps() has always computed this and then immediately added lambda to it,
    throwing the split away. The split is the interesting half: lambda is one
    number for the whole system and says nothing about location, so every
    difference between two buses lives here. A view that colours a map by LMP
    shows where power is dear; a view that colours it by this shows WHY.

    It is zero at the slack by construction -- PTDF[l, slack] = 0 for every
    line -- which is the entire content of the slack choice (trap 2). Read the
    two components together and a slack change is visible; read the LMP alone
    and it is not, because the LMP does not move.
    """
    row = {l: j for j, l in enumerate(lines)}
    col = {b: j for j, b in enumerate(buses)}
    mu = congestion_prices(res)

    return {
        (i, t): float(sum(PTDF[row[l], col[i]] * mu[l, t] for l in lines))
        for i in buses
        for t in _hours(res)
    }


def lmps(res, buses, lines, PTDF, island_of):
    """Locational Marginal Price - Cost of serving one more MW of load at a bus, including congestion.

    {(bus, t): $/MWh}.

    island_of is {bus: island}, and it is what makes this work on a cut
    network: a bus is priced against ITS OWN market's lambda, not against a
    system lambda that no longer exists. For a connected network every bus
    maps to the same island and the sum below is M4's, unchanged.
    """
    # float() because PTDF is a numpy array and its scalars carry through the
    # sum. np.float64 compares and prints the same, but it leaks numpy into
    # every downstream consumer -- settlement, the figures, a JSON dump of a
    # run -- for no benefit.
    cong = congestion(res, buses, lines, PTDF)
    return {
        (i, t): float(res["lmbda"][island_of[i], t] + cong[i, t])
        for i in buses
        for t in _hours(res)
    }


def generator_status(res, Pmax, tol=1e-6):
    """Where each generator sits in its own range. {(gen, t): str}.

    One of three words, and it is a statement about DISPATCH, not about price:

        "off"        p == 0.        Offered, not taken.
        "interior"   0 < p < Pmax.  The LP could move it either way.
        "at_max"     p == Pmax.     Taken in full; it would sell more.

    This replaces an earlier marginal_units(), which returned the interior
    units under the name "marginal" and so made a PRICE claim out of a
    DISPATCH test. The two are not the same question, and case5 at its peak
    hour shows the gap in both directions: two units are interior at once
    (DE binds, so E is its own pricing region and Brighton and Solitude each
    set their own bus's price), while three of five buses have an LMP equal to
    no offer at all, because a congested bus is priced by a combination the
    PTDF assembles and not by any single machine.

    Status says where a unit is. reduced_cost() says what that is worth. Read
    together they support the conclusion; neither states it alone.

    tol is MW, and guards a solver returning 1e-13 for zero. It is not a
    "close enough to the cap" band: a unit 0.5 MW below its cap is interior,
    and the price knows it.
    """
    out = {}
    for (g, t), p in res["p"].items():
        if p <= tol:
            out[g, t] = "off"
        elif p >= Pmax[g] - tol:
            out[g, t] = "at_max"
        else:
            out[g, t] = "interior"
    return out


def headroom(res, Pmax):
    """Unused capacity. {(gen, t): MW}. Pmax - p, and nothing cleverer.

    Returned rather than left to the caller because the caller is a browser,
    and the boundary rule says the browser formats numbers and does not
    compute them. A subtraction is a small thing to hand over; a SECOND place
    where Pmax and p are combined is not.
    """
    return {(g, t): float(Pmax[g] - p) for (g, t), p in res["p"].items()}


def reduced_costs(lmp, cost, gen_bus, hours):
    """What one more MW is worth to each generator. {(gen, t): $/MWh}.

        reduced_cost[g, t] = LMP[bus of g, t] - offer[g]

    The sign is the whole content, and it is the LP's own optimality condition
    written in money:

        > 0   the price at its bus beats its offer, so it wants to sell more.
              An optimal solve has it at_max; anything else means capacity is
              being left on the table and the answer is wrong.

        = 0   indifferent. The unit is interior, and its offer IS the price at
              its bus. This is the honest version of "marginal".

        < 0   the price does not cover its offer, so it is off.

    Which makes this a self-check as much as a display field: status and sign
    must agree, and tests/test_w0_http.py asserts they do at every hour. A
    disagreement is a dual extraction bug, and it is the kind that returns
    plausible numbers.

    One case looks like a contradiction and is not: at_max WITH a reduced cost
    of zero. The unit is full and indifferent at the same time, which means
    load has landed exactly on a capacity breakpoint and the price there is an
    interval rather than a number -- trap 3, the degenerate case M0 asserts
    bounds at instead of values. Detecting it is free; reporting the interval
    is not, and that is a W3 decision.
    """
    return {
        (g, t): float(lmp[gen_bus[g], t] - cost[g])
        for g in cost
        for t in hours
    }


def price_uniqueness(
    gen_status,
    gen_bus,
    served,
    bid_mw,
    bid_value,
    bid_bus,
    mu,
    islands,
    island_lines,
    hours,
    mw_tol=1e-6,
    mu_tol=1e-9,
):
    """Whether the optimum pins one price and one dispatch. {(island, t): str}.

    One basic variable is needed per active row. Count both, per island and
    per hour, and the comparison is the answer:

        basic = generators strictly inside their bounds
              + priced bids strictly between 0 and the quantity they asked for

        rows  = 1  +  lines in this island whose mu is non-zero
                ^          ^
         the island's   each binding limit is
         balance row    an active row

        basic < rows    a row has no variable free to set its price, so the
                        dual has room to move: lambda is an INTERVAL and the
                        returned number is one end of it.

        basic == rows   both pinned.

        basic > rows    spare variables sit at zero reduced cost. The price is
                        unique and WHO RUNS is not.

    The two directions are different sentences and do not collapse into one
    "degenerate" flag. Measured on case5 with every offer at $25 and both
    limits removed: lambda is 25 under slack A and slack C alike, while alta
    and park_city sit off at a reduced cost of zero and could swap in at no
    cost. The price was never in doubt there; the dispatch was.

    Nothing here solves anything. Every input is a field clear() already
    returns, which is what makes this a count rather than a second
    optimization. Returning the interval itself is a second optimization --
    two LPs per island-hour to maximize and minimize lambda over the dual
    feasible set -- and is deferred to W4.

    Only PRICED bids count. An inelastic bid is a constant on the balance row,
    not a variable, so it can hold nothing.

    The flag inherits the flicker rather than curing it. It reads mu against
    mu_tol and dispatch against mw_tol, so within a pixel of a breakpoint the
    flag itself moves between answers. That is trap 3 one level up, and the
    rule is unchanged: do not smooth it.
    """
    priced = [k for k in bid_value if bid_value[k] is not None]

    out = {}
    for home, group in islands.items():
        here = set(group)
        gens_here = [g for g, bus in gen_bus.items() if bus in here]
        bids_here = [k for k in priced if bid_bus[k] in here]
        lines_here = island_lines[home]

        for t in hours:
            basic = sum(1 for g in gens_here if gen_status[g, t] == "interior")
            basic += sum(
                1
                for k in bids_here
                if mw_tol < served[k, t] < bid_mw[k, t] - mw_tol
            )
            rows = 1 + sum(1 for l in lines_here if abs(mu[l, t]) > mu_tol)

            if basic < rows:
                verdict = "price_is_an_interval"
            elif basic > rows:
                verdict = "dispatch_is_not_unique"
            else:
                verdict = "unique"
            out[home, t] = {"basic": basic, "rows": rows, "verdict": verdict}

    return out
