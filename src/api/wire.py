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
        "lmbda": [_num(cleared["lmbda"][t]) for t in hours],
        "cost": _num(cleared["cost"]),
        # Column arrays, same alignment rule as every other series. The
        # residual is here and is meant to be displayed: it is the claim the
        # repo rests on, and a site that hides it is doing the thing this repo
        # exists to not do.
        "settlement": {
            f: [_num(settlement[t][f]) for t in hours] for f in fields
        },
        "PTDF": [[float(v) for v in row] for row in cleared["PTDF"]],
    }
