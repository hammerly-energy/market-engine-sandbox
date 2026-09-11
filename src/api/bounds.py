"""What a public POST body is allowed to contain.

This is half of W0 and it is not transport plumbing. A live HiGHS solve behind
a public URL is a resource-exhaustion vector: the cost of a request is set by
the body, and nothing in src/model/ has any reason to care how big a Scenario
is. Something has to say no, and this is the only place that can, because it
is the last point at which the input is still a dict.

Three rules:

    REJECT, NEVER TRUNCATE.  A body over a cap is refused by name. Silently
    dropping the 21st bus would return a priced solve of a network the caller
    did not send, which is worse than an error -- it is a wrong answer wearing
    a 200.

    BOUND THE SOLVE, NOT THE BYTES ALONE.  Body size is a proxy and a poor
    one; a 2 KB config can declare a 24-hour horizon on 40 buses. The caps
    below are on the things that multiply into LP rows: buses, branches,
    generators, hours.

    NO SOURCE MAY REACH THE NETWORK.  load.source = eia930 would make an HTTP
    handler call a live EIA endpoint with the server's API key, once per POST,
    for free, on a stranger's say-so. Only the two declarative sources are
    allowed over the wire. This is not a size limit and it is the most
    important line in the file.

The numbers are deliberately generous against the thing being served -- the
five-bus teaching case -- and mean against a stranger. A 20-bus, 40-branch,
24-hour LP solves in well under a second, so a caller at the cap costs about
what case5 costs; two orders of magnitude above it does not.
"""

import math

MAX_BODY_BYTES = 64 * 1024
MAX_BUSES = 20
MAX_BRANCHES = 40
MAX_GENERATORS = 40
MAX_HOURS = 24
MAX_BIDS = 40

# eia930 is excluded on purpose. See the module docstring.
ALLOWED_LOAD_SOURCES = ("static", "profile", "blocks")


class BadRequest(Exception):
    """A body this server will not solve. Carries a code and an HTTP status.

    Every rejection is named. `code` is a stable string a frontend can switch
    on; `detail` is a sentence a visitor can read. Neither is ever a traceback.
    """

    def __init__(self, code, detail, status=422):
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status = status


def check_body_size(nbytes):
    if nbytes > MAX_BODY_BYTES:
        raise BadRequest(
            "body_too_large",
            f"request body is {nbytes} bytes; the limit is {MAX_BODY_BYTES}",
            status=413,
        )


def _finite(value, where):
    """Reject NaN and infinity wherever a real number is expected.

    Python's json module parses the non-standard literals NaN, Infinity and
    -Infinity without complaint, so they arrive as ordinary floats. NaN in a
    cost coefficient does not raise anywhere downstream -- it solves, and it
    returns prices that are all NaN, which is the confident-wrong-answer
    failure mode Branch.__post_init__ exists to prevent for reactance.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BadRequest("invalid_scenario", f"{where} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise BadRequest("invalid_scenario", f"{where} must be finite, got {value}")
    return float(value)


def _limit(value, where):
    """A line rating. None and the string 'inf' both mean unlimited.

    JSON has no infinity literal, and configs/m3.yaml writes an unlimited line
    as .inf, so the wire needs a spelling for it. Two are accepted because a
    hand-written client reaches for null and a config translated from YAML
    reaches for "inf"; neither should have to know which one this server
    happens to prefer.
    """
    if value is None or (isinstance(value, str) and value.strip().lower() in ("inf", "infinity")):
        return math.inf
    return _finite(value, where)


def _count(items, cap, what):
    if len(items) > cap:
        raise BadRequest(
            "too_many_" + what,
            f"{len(items)} {what} requested; the limit is {cap}",
        )


def normalize(config):
    """Validate a config dict against the caps and return it solve-ready.

    Returns a NEW dict with the wire spellings of infinity resolved to floats.
    The input is not mutated, and nothing here computes anything a market
    would recognise -- it counts things and checks types. scenario_from_config
    still does all the real validation afterwards, and its ValueErrors are
    just as displayable; these checks exist for the failures that would cost a
    solve before it got there.
    """
    if not isinstance(config, dict):
        raise BadRequest("invalid_scenario", "config must be an object")

    out = dict(config)
    out.setdefault("name", "web")

    fleet = out.get("fleet")
    if not isinstance(fleet, dict) or not fleet:
        raise BadRequest("invalid_scenario", "fleet must be a non-empty object")
    _count(fleet, MAX_GENERATORS, "generators")

    net = out.get("network")
    if not isinstance(net, dict):
        raise BadRequest(
            "invalid_scenario",
            "network is required: this endpoint prices a nodal market, and a "
            "config with no network has no buses to price at",
        )
    buses = net.get("buses")
    if not isinstance(buses, list) or not buses:
        raise BadRequest("invalid_scenario", "network.buses must be a non-empty list")
    _count(buses, MAX_BUSES, "buses")

    branches = net.get("branches") or {}
    if not isinstance(branches, dict):
        raise BadRequest("invalid_scenario", "network.branches must be an object")
    _count(branches, MAX_BRANCHES, "branches")

    net = dict(net)
    net["branches"] = {
        name: dict(spec, limit_mw=_limit(spec.get("limit_mw"), f"branch {name} limit_mw"))
        if isinstance(spec, dict)
        else spec
        for name, spec in branches.items()
    }
    out["network"] = net

    load = out.get("load")
    if not isinstance(load, dict):
        raise BadRequest("invalid_scenario", "load must be an object")
    source = load.get("source")
    if source not in ALLOWED_LOAD_SOURCES:
        raise BadRequest(
            "unsupported_load_source",
            f"load.source must be one of {list(ALLOWED_LOAD_SOURCES)}, got "
            f"{source!r}. Sources that fetch from a live API are not reachable "
            f"over HTTP.",
        )
    if source in ("profile", "blocks"):
        shape = load.get("shape")
        if not isinstance(shape, list) or not shape:
            raise BadRequest("invalid_scenario", "load.shape must be a non-empty list")
        _count(shape, MAX_HOURS, "hours")
    if source == "blocks":
        bids = load.get("bids")
        if not isinstance(bids, dict) or not bids:
            raise BadRequest("invalid_scenario", "load.bids must be a non-empty object")
        # Bids are LP columns exactly as generators are, and two bids at one
        # bus is a demand curve rather than a mistake -- so they are capped by
        # count, not by bus.
        _count(bids, MAX_BIDS, "bids")

    return out


def normalize_limits(limits):
    """The limit-override argument to clear(). {line: MW}, inf allowed."""
    if limits is None:
        return None
    if not isinstance(limits, dict):
        raise BadRequest("invalid_scenario", "limits must be an object")
    _count(limits, MAX_BRANCHES, "branches")
    return {
        str(line): _limit(mw, f"limits[{line}]") for line, mw in limits.items()
    }
