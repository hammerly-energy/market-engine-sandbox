"""Assemble LMPs from dispatch duals.

    LMP[i] = lambda + sum_over_lines( PTDF[l, i] * mu[l] )  [+ loss term]

Sign convention follows how the flow constraint was written. Verify against a
case with a published answer."""

import math


def congestion_prices(res):
    """Dual on a line's flow limit. {(line, t): $/MWh}, signed.

    One number per line, from the two raw duals, and the sign is the content:

        mu = mu_up - mu_dn        mu > 0  the lower limit is holding
                                  mu < 0  the upper limit is holding

    |mu| is what one more MW of rating is worth. mu is not, and the difference
    is a sign rather than a rounding -- a line binding the other way returns a
    negative number, and prose that calls mu "the worth" prints a negative
    price for a positive saving. Measured on w1.yaml over the day:

        AB rated 150    sum mu = -943.9018    raising it 1 MW saves $943.9018
        DE rated 240    sum mu = +979.4908    raising it 1 MW saves $979.4908

    Exact to every digit in both directions. case5's own binding line is DE,
    at its lower limit, which is why the positive case is the one the repo saw
    first -- and why the settlement identity is written with the flow rather
    than the limit (CLAUDE.md).
    """
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
    shows where power is dear; a view that colours it by this shows why.

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
    network: a bus is priced against its own market's lambda, not against a
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

    One of three words, and it is a statement about dispatch, not about price:

        "off"        p == 0.        Offered, not taken.
        "interior"   0 < p < Pmax.  The LP could move it either way.
        "at_max"     p == Pmax.     Taken in full; it would sell more.

    This replaces an earlier marginal_units(), which returned the interior
    units under the name "marginal" and so made a price claim out of a
    dispatch test. The two are not the same question, and case5 at its peak
    hour shows the gap in both directions: two units are interior at once
    (DE binds, so E is its own pricing region and E1 and C1 each
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
    compute them. A subtraction is a small thing to hand over; a second place
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

    One case looks like a contradiction and is not: at_max with a reduced cost
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
    flows,
    Fmax,
    lmp,
    reduced_cost,
    gen_pmax,
    islands,
    island_lines,
    hours,
    mw_tol=1e-6,
    mu_tol=1e-9,
    rc_tol=1e-9,
):
    """Whether the optimum pins one price and one dispatch. {(island, t): str}.

    One basic variable is needed per active row. Count both, per island and
    per hour, and the comparison is the answer:

        basic = generators strictly inside their bounds
              + priced bids strictly between 0 and the quantity they asked for

        rows  = 1  +  lines in this island sitting at a rating
                ^          ^
         the island's   each active flow limit
         balance row    is a row

    A row is counted from the PRIMAL -- the flow is at the rating -- and not
    from mu. They usually agree, and mu != 0 does imply the flow is at its
    limit, so the two are unioned below and the dual can only ever add a row
    the primal test already found. But the converse fails, and it fails in the
    direction that matters: a line can sit exactly at its rating with mu = 0,
    which is an active row holding a dual that is free to move. Counting by mu
    misses it, under-counts rows, and reports "unique" at precisely the knife
    edge this function exists to find. Measured on configs/w1.yaml, hour 18,
    with DE rated at the 282.84 MW it carries when unrated:

        mu[DE] = 0.0, f[DE] = -282.84033 = -rating exactly

        bus   LMP      dCost/dLoad from below   from above
         B   30.0000          26.3845            30.0000
         D   30.0000          30.0000            39.9427

    The price at D is an interval $9.94 wide and the old count called it
    unique.

        basic < rows    a row has no variable free to set its price, so the
                        dual has room to move: lambda is an interval and the
                        returned number is one end of it.

        basic == rows   both pinned.

        basic > rows    more variables are free than there are rows to pin
                        them, so the optimum is a face and not a vertex.

    That last test is not the only way the dispatch goes free, and on its own
    it misses the ordinary one: a variable sitting AT a bound whose reduced
    cost is zero. The objective is flat in the direction its bound allows, so
    it can be moved in at no cost and the answer is one of several. Counted
    here as `tied` -- generators off or at_max with |LMP - offer| ~ 0, and
    priced bids at a bound whose valuation equals the LMP at their bus.

    THE TIED COUNT IS ONLY READ WHEN THE PRICE IS UNIQUE, and that gate is
    what makes it sound rather than merely suggestive. A reduced cost is
    measured against lambda, so when lambda is an interval it is measured
    against one arbitrary end of it and a zero carries no information.
    Measured on configs/w1.yaml with both limits removed:

        hour 8    A2 at_max, rc 0.0, basic 0 < rows 1
                  perturbing every offer by +/-1e-4 moves no dispatch at all.
                  The dispatch is unique; the zero is an artifact of lambda
                  being [15, 30] and rc being computed at 15.

        hour 20   A2 at_max, rc 0.0, basic 2 == rows 2, AD/DE rated
                  three distinct dispatches share a cost of 21900.000000.
                  The dispatch really is one of several.

    Same signal, opposite truth, told apart by the gate and by nothing else.

    So a "price_is_an_interval" verdict says nothing about the dispatch. It is
    not a claim that the dispatch is unique -- it is a refusal to make one
    from fields that cannot support it.

    The two directions are different sentences and do not collapse into one
    "degenerate" flag. Measured on case5 with every offer at $25 and both
    limits removed: lambda is 25 under slack A and slack C alike, while A1
    and A2 sit off at a reduced cost of zero and could swap in at no
    cost. The price was never in doubt there; the dispatch was.

    Nothing here solves anything. Every input is a field clear() already
    returns, which is what makes this a count rather than a second
    optimization. Returning the interval itself is a second optimization --
    two LPs per island-hour to maximize and minimize lambda over the dual
    feasible set -- and is deferred to W4.

    Only priced bids count. An inelastic bid is a constant on the balance row,
    not a variable, so it can hold nothing.

    The flag inherits the flicker rather than curing it. It reads mu against
    mu_tol and dispatch against mw_tol, so within a pixel of a breakpoint the
    flag itself moves between answers. That is trap 3 one level up, and the
    rule is unchanged: do not smooth it.
    """
    priced = [k for k in bid_value if bid_value[k] is not None]

    def _tied(gens_here, bids_here, t):
        """Variables at a bound the objective is indifferent about moving.

        A unit whose capacity is zero is skipped: its two bounds coincide, so
        it cannot move however flat the objective is, and counting it would
        report an ambiguity that has nowhere to go. Same for a bid asking for
        nothing this hour.
        """
        n = 0
        for g in gens_here:
            if gen_pmax[g] <= mw_tol:
                continue
            if gen_status[g, t] != "interior" and abs(reduced_cost[g, t]) <= rc_tol:
                n += 1
        for k in bids_here:
            asked = bid_mw[k, t]
            if asked <= mw_tol:
                continue
            got = served[k, t]
            at_bound = got <= mw_tol or got >= asked - mw_tol
            if at_bound and abs(lmp[bid_bus[k], t] - bid_value[k]) <= rc_tol:
                n += 1
        return n

    def _active(l, t):
        """Is this line's flow limit holding? Primal first, dual as a union.

        An unrated line has Fmax = inf and no flow reaches it, so it is never
        active -- which is the same statement line_loading() makes when it
        maps f / inf to zero.
        """
        limit = float(Fmax[l])
        if abs(flows[l, t]) >= limit - mw_tol:
            return True
        return abs(mu[l, t]) > mu_tol

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
            rows = 1 + sum(1 for l in lines_here if _active(l, t))

            tied = _tied(gens_here, bids_here, t)

            if basic < rows:
                verdict = "price_is_an_interval"
            elif basic > rows or tied:
                verdict = "dispatch_is_not_unique"
            else:
                verdict = "unique"
            out[home, t] = {
                "basic": basic,
                "rows": rows,
                "tied": tied,
                "verdict": verdict,
            }

    return out


def line_loading(res, Fmax):
    """Signed loading. {(line, t): f / limit, on [-1, 1]}.

    The variable a diverging colour ramp needs, and the reason it is computed
    here rather than in the browser is the boundary rule: a division is small,
    a second place where a flow and a rating are combined is not.

    Signed, and on [-1, 1] rather than a percent of rating:

        f / limit  carries direction and loading in one number. Percent of
                   rating runs 0 to 100 and is natively sequential, so a
                   diverging ramp drawn from it would have no midpoint to
                   diverge about.

    An unrated line is f / inf = 0 and reads as idle forever. That is the
    honest answer to "how close is this line to its limit" for a line that has
    none; a view that wants to say the flow is large says it with the flow.

    Clamped because the solver returns 240.00000000000003 for a line at 240,
    and a ramp indexed past its own domain is a colour nobody chose.
    """
    out = {}
    for (l, t), f in res["f"].items():
        limit = float(Fmax[l])
        x = 0.0 if math.isinf(limit) or limit <= 0 else float(f) / limit
        out[l, t] = min(max(x, -1.0), 1.0)
    return out
