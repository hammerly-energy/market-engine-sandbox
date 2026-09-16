# Market Engine Sandbox

An electricity market clearing engine, built from scratch. Given generator
offers, a load forecast, and a transmission network with limits, it answers
who runs, at what output, and what a MWh is worth at each bus.

Rewire the network in the browser and the prices move. Every solve is live:
the levers include adding a bus and connecting a line, so there is no
precomputed sweep behind this page.

## What a Price Is Here

Prices are dual variables. The dual on the energy balance constraint is the
marginal cost of serving one more MW, and that is the price — it is not
computed by a pricing rule, it falls out of the optimization.

    LMP[i] = λ + Σ PTDF[l,i] · μ[l]

λ is the dual on the island's energy balance and is the same at every bus in
that island. μ[l] is the dual on line l's flow limit, zero unless the line is
binding, and its sign carries which direction the line binds in. The sum is
the congestion component.

The page displays the settlement residual rather than hiding it:

    payments − revenue = −Σ μ[l] · f[l]

Both sides are reached independently — once from the money, once from the
duals — and the residual is the claim that they agree. It is asserted per
island and per hour, never summed, because a positive residual in one hour
would otherwise cancel a negative one in another.

## Scope

A nodal energy market, DC approximation, 24-hour day-ahead solve, on a
five-bus teaching case with five synthetic generators and cost-based offers.

What is **not** modelled, and is not hidden in a footer:

- **No unit commitment.** No startup cost, no minimum up or down time, no
  minimum stable output. A pure LP will part-load a unit at any level.
- **No storage and no reserves.**
- **No losses.** The DC approximation is lossless, so the marginal loss
  component of a real LMP is absent — it is zero here, not small.
- **No validation against published prices.** Absolute levels will be wrong;
  the fleet is synthetic. What should match real markets is structure — when
  prices separate, when the evening ramp bites, which hours go negative.

An LMP here is not bounded by the offer cap, and that is correct rather than a
bug. The cap bounds a bid; an LMP is λ plus a shadow price on a line, and the
second term has no bound in either direction. Clipping it would break the
settlement identity, so the range is disclosed instead.

## Running It Locally

    pip install .
    uvicorn src.api.app:app --reload --port 8000

Then open `http://localhost:8000`.

## Layout

    src/network/    susceptance matrix, PTDF shift factors
    src/model/      dispatch LP, pricing from the duals
    src/settle/     the settlement identity
    src/api/        FastAPI over clear(). transport only, no maths
    web/            the browser build. no toolchain, no build step
    configs/        one YAML file per scenario, fully declarative
    tests/          test_<milestone>_<context>.py

No market arithmetic happens in JavaScript. The browser formats numbers and
positions marks; every number on screen is a field of the `clear()` return.
A second implementation of the LMP assembly, in a second language, would be a
new place for a sign convention to be wrong.

## Deploy Notes

This branch adds the container and a per-address rate limit on `/clear`, the
only endpoint that starts a solve. Input bounds were already in place: 64 KB
body, at most 20 buses, 40 branches, 40 generators, 40 bids and 24 hours,
each rejected by name rather than truncated.

`MARKET_ENGINE_MAX_SOLVES_PER_MIN` (default 30) and `MARKET_ENGINE_ORIGINS`
(default `*`) are the two knobs a deploy has.

## Licence

MIT.
