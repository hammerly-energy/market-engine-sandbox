"""POST /clear: a scenario config in, a priced and settled day out.

This module is transport and nothing else. It reads bytes, refuses the ones it
will not solve, hands a dict to scenario_from_config(), calls clear(), and
encodes the result. It adds no number that clear() did not return, and the
test suite asserts exactly that -- the HTTP body must match the in-process
result field for field.

    bytes --> size cap --> json --> bounds.normalize --> scenario_from_config
                                                               |
      JSON  <-- wire.encode <---------- clear(scenario, slack=, limits=)

Errors are named, never traced. Every failure leaves here as

    {"error": "<stable code>", "detail": "<a sentence a visitor can read>"}

with a 4xx, because every failure this endpoint can have is a statement about
the body it was sent. An unexpected exception is the exception: it is a 500
with no detail, because a detail there would be a traceback and a traceback on
a public URL is an information leak, not an error message.
"""

import json
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api import bounds, wire
from src.api.bounds import BadRequest
from src.ingest.scenario import scenario_from_config
from src.model.clearing import clear

app = FastAPI(
    title="market-engine",
    description="A nodal DC market clearing engine. LP dispatch, duals as prices.",
    version="0.5.0",
)

# The editor is a static page and will not always share an origin with this
# process. /clear reads nothing, writes nothing, and holds no session, so
# there is no cookie or credential for a cross-origin caller to ride on -- the
# open default costs nothing here. Narrow it with MARKET_ENGINE_ORIGINS on a
# deploy that wants to.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("MARKET_ENGINE_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)


def _error(exc):
    return JSONResponse(
        status_code=exc.status, content={"error": exc.code, "detail": exc.detail}
    )


async def _read_capped(request):
    """The body, or a 413 -- WITHOUT buffering an unbounded one first.

    await request.body() reads to completion before anything can inspect the
    size, so a caller that sends 2 GB has already cost 2 GB of memory by the
    time a size check runs. Streaming and stopping at the cap is the whole
    point; Content-Length is checked too, but it is a claim by the client and
    is not the defence.

    This bounds one request. It is not a defence against many slow ones at
    once -- that is a reverse proxy's job, and saying so here is cheaper than
    someone later assuming this file already did it.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit():
        bounds.check_body_size(int(declared))

    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        bounds.check_body_size(size)
        chunks.append(chunk)
    return b"".join(chunks)


@app.get("/health")
def health():
    """Liveness. Does not solve, so it says nothing about the solver."""
    return {"status": "ok"}


@app.get("/limits")
def limits():
    """The caps a body must respect, so a client can refuse before it posts."""
    return {
        "max_body_bytes": bounds.MAX_BODY_BYTES,
        "max_buses": bounds.MAX_BUSES,
        "max_branches": bounds.MAX_BRANCHES,
        "max_generators": bounds.MAX_GENERATORS,
        "max_hours": bounds.MAX_HOURS,
        "load_sources": list(bounds.ALLOWED_LOAD_SOURCES),
    }


@app.post("/clear")
async def post_clear(request: Request):
    """Clear, price and settle one scenario.

    Body: {"config": {...}, "slack": "D" | null, "limits": {"DE": 240.0} | null}

    config is the same declarative shape as configs/*.yaml, because the YAML
    files ARE this dict -- the editor posts what a config file says, and the
    two paths into scenario_from_config stay one code path. slack and limits
    are clear()'s own arguments, passed through: the slack is a choice this
    layer makes (trap 2), and limits is the line-rating slider.
    """
    try:
        raw = await _read_capped(request)
    except BadRequest as exc:
        return _error(exc)

    try:
        body = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _error(BadRequest("malformed_json", f"body is not valid JSON: {exc}", 400))

    if not isinstance(body, dict):
        return _error(BadRequest("malformed_json", "body must be a JSON object", 400))

    try:
        config = bounds.normalize(body.get("config"))
        limits = bounds.normalize_limits(body.get("limits"))
        slack = body.get("slack")
        if slack is not None and not isinstance(slack, str):
            raise BadRequest("invalid_scenario", "slack must be a bus name or null")

        scenario = scenario_from_config(config, origin="POST /clear")
        cleared = clear(scenario, slack=slack, limits=limits)
    except BadRequest as exc:
        return _error(exc)
    except ValueError as exc:
        # Everything src/model/ refuses by design arrives here: a disconnected
        # network, a slack that is not a bus, a zero reactance, a duplicate
        # name. Those messages were written to be read by a person -- see the
        # table in CLAUDE.md -- so they are passed through verbatim rather
        # than replaced with something vaguer.
        return _error(BadRequest("invalid_scenario", str(exc)))
    except RuntimeError as exc:
        # Today this is only "solve not optimal: infeasible", which means the
        # fleet cannot serve the load. PROVISIONAL. W1 decides what a market
        # says when load cannot be served -- refuse, or admit a scarcity price
        # and let lambda rise to it -- and that decision belongs in the engine,
        # not here. This exists so the answer today is a named 4xx instead of
        # a traceback, and it should be revisited, not built on.
        return _error(BadRequest("solve_failed", str(exc)))

    return wire.encode(cleared)


# ------------------------------------------------------------------- the page
# Mounted LAST, and that ordering is load-bearing. A mount at "/" catches every
# path, so it must be registered after /health, /limits and /clear or it would
# shadow them -- Starlette matches routes in registration order.
#
# Serving the editor from this process means the browser and the solver share
# an origin, so the CORS middleware above is not what makes the site work; it
# is there for a deploy that puts the static files somewhere else.
#
# The directory is resolved from this file, not from the working directory, so
# `uvicorn src.api.app:app` works from anywhere in the repo.
WEB_DIR = Path(__file__).resolve().parents[2] / "web"
if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
