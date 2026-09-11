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
