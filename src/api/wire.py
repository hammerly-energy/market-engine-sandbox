"""clear()'s return, shaped so JSON can carry it. No arithmetic.

Two things in the engine's return cannot cross a wire, and both are format,
not meaning:

    TUPLE KEYS.   dispatch, flows, mu, lmp and congestion are keyed by
                  (name, hour). A JSON object key is a string, so {("A", 18):
                  30.0} has no spelling. Nesting it as {"A": {"18": 30.0}}
                  would work and is what most APIs do -- and it loses the hour
                  TYPE on the way, because "18" is not 18 and "static" is not
                  a number at all. This repo's hours are integers at M4,
                  the literal string "static" at M3, and ISO-8601 UTC strings
                  at M2, and the frontend must not have to guess which.

                  So: one array per name, POSITIONALLY ALIGNED to "hours".

                      hours:    [0, 1, 2, ...]
                      lmp:      {"A": [10.0, 10.0, 16.98, ...]}
                                        ^        ^
                                     hours[0] hours[1]

                  The hour labels survive in exactly one place, with their own
                  types intact, and every series is read by index against it.

    INFINITY.     An unlimited line is limit_mw = inf. JSON has no literal for
                  it. Python's json module will happily emit the non-standard
                  token Infinity, which JSON.parse() then rejects -- a failure
                  that appears in the browser, not here. Unlimited goes on the
                  wire as null, which is what bounds.py accepts coming back.

Nothing else changes. Every number below is a field of the clear() return,
copied. This module adds no market arithmetic, and the frontend does none
either -- that is the boundary rule, and this file is the seam it runs along.
"""

import math


def _num(x):
    """A float JSON.parse() can read. Unlimited becomes null."""
    x = float(x)
    if math.isinf(x):
        return None
    if math.isnan(x):
        # Unreachable from a solved LP; a NaN here would mean the engine
        # returned one, and shipping it as a silent null would hide that.
        raise ValueError("NaN in a cleared result")
    return x


def _nullable(x):
    """A number that is allowed to be absent. None crosses as null.

    Only bid_value uses this. None there means INELASTIC -- a bid that must
    be served and therefore has no price at which it would walk away -- and
    that is a claim, not a missing value. Coercing it to a number would
    invent a willingness to pay; dropping the key would make the frontend
    guess from the key's absence.
    """
    return None if x is None else _num(x)


def _series(keyed, names, hours):
    """{(name, hour): value} -> {name: [value per hour]}, aligned to hours."""
    return {n: [_num(keyed[n, t]) for t in hours] for n in names}


def encode(cleared):
    """The JSON-safe body of a cleared market.

    Field for field the same information as clear() returns, re-shaped and
    nothing more. PTDF comes across as a plain nested list in [line][bus]
    order, which is the order "lines" and "buses" already declare -- the
    frontend needs it to show why a bus is priced the way it is, and
    reconstructing it in JavaScript would be exactly the second implementation
    the boundary rule exists to prevent.
    """
    hours = list(cleared["hours"])
    buses = list(cleared["buses"])
    lines = list(cleared["lines"])
    gens = list(cleared["gen_bus"])

    bids = list(cleared["bid_bus"])
    islands = list(cleared["islands"])
    settlement = cleared["settlement"]
    fields = ("payments", "revenue", "congestion_rent", "rent_from_duals", "residual")

    return {
        "buses": buses,
        "lines": lines,
        "generators": gens,
        "slack": cleared["slack"],
        # The hour labels, with their types. Every array below is read against
        # this one by position.
        "hours": hours,
        "limits": {l: _num(cleared["limits"][l]) for l in lines},
        "gen_bus": dict(cleared["gen_bus"]),
        "gen_cost": {g: _num(v) for g, v in cleared["gen_cost"].items()},
        "gen_pmax": {g: _num(v) for g, v in cleared["gen_pmax"].items()},
        "dispatch": _series(cleared["dispatch"], gens, hours),
        "headroom": _series(cleared["headroom"], gens, hours),
        "reduced_cost": _series(cleared["reduced_cost"], gens, hours),
        # Strings, so _series (which floats everything) is not the right tool.
        # Same alignment rule: one array per generator, indexed by "hours".
        "gen_status": {
            g: [cleared["gen_status"][g, t] for t in hours] for g in gens
        },
        "flows": _series(cleared["flows"], lines, hours),
        "mu": _series(cleared["mu"], lines, hours),
        "lmp": _series(cleared["lmp"], buses, hours),
        "congestion": _series(cleared["congestion"], buses, hours),
        # One market per island, named by its slack. A connected network has
        # exactly one entry and a cut one has several -- never a bare array,
        # because a shape that changes with the topology is a shape the
        # frontend has to branch on, and it would branch wrong the first time
        # someone cut a line.
        "islands": {home: list(group) for home, group in cleared["islands"].items()},
        "island_of": dict(cleared["island_of"]),
        "island_lines": {k: list(v) for k, v in cleared["island_lines"].items()},
        "lmbda": {s: [_num(cleared["lmbda"][s, t]) for t in hours] for s in islands},
        "bids": bids,
        "bid_bus": dict(cleared["bid_bus"]),
        # null means inelastic: must be served, no price at which it walks.
        "bid_value": {k: _nullable(v) for k, v in cleared["bid_value"].items()},
        # What each bid ASKED for, against what it GOT. Equal for every bid
        # in an unconstrained hour; the gap is curtailment, and it is the
        # only place on the wire where a market declining to serve someone is
        # visible. A view that shows demand without showing this shows a
        # market that always clears, which is the thing W1 stopped being true.
        "bid_mw": _series(cleared["bid_mw"], bids, hours),
        "served": _series(cleared["served"], bids, hours),
        "cost": _num(cleared["cost"]),
        "benefit": _num(cleared["benefit"]),
        # Column arrays, same alignment rule as every other series. The
        # residual is here and is meant to be displayed: it is the claim the
        # repo rests on, and a site that hides it is doing the thing this repo
        # exists to not do.
        # Per island AND per hour. Summing the islands would let a positive
        # residual in one cancel a negative one in the other, which is the
        # per-hour mistake one dimension over.
        "settlement": {
            s: {f: [_num(settlement[s, t][f]) for t in hours] for f in fields}
            for s in islands
        },
        "PTDF": [[float(v) for v in row] for row in cleared["PTDF"]],
    }
