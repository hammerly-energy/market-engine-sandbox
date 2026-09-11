/* Editor state: the single source of truth the eight levers mutate.
 *
 * Nothing else in web/ holds state. A lever is a function from this object to
 * a new one, and every render reads from here -- so "what is on screen" and
 * "what would be posted" can never drift apart, which is the failure this
 * module exists to prevent.
 *
 *   state --toConfig()--> the exact dict shape of configs/w1.yaml --POST-->
 *            \--toLimits()--> clear()'s limits= argument
 *             \--coords stay here, and never cross the wire
 *
 * TWO THINGS ARE DELIBERATE AND BOTH ARE MARKET DECISIONS, NOT UI DETAILS.
 *
 * 1. toConfig ALWAYS emits load.source = "blocks". W1's fuzz measured it:
 *    over 120 random topologies, a mixed elastic/inelastic demand side was
 *    infeasible 31 times and an all-priced one 0 times, because d = 0, p = 0
 *    is feasible on any network. An editor that can build any topology while
 *    insisting its load must be served is an editor whose most ordinary move
 *    is an error message. So the editor emits only blocks -- see CLAUDE.md,
 *    "the editor emits only blocks configs".
 *
 * 2. The slack is carried in state and posted EXPLICITLY on every request,
 *    and it is written into network.slack too so the config and the argument
 *    cannot disagree. The editor owns the bus list, so a slack naming a
 *    deleted bus is a client bug and the engine's 422 is what catches it
 *    (W2.6). The engine's own fallback is for callers with no dropdown.
 *
 * No market arithmetic lives here or anywhere else in web/. This module
 * reshapes declarations; it never computes a price, a flow or a residual.
 */

/* Unlimited is null in editor state. JSON has no infinity literal, and
   bounds.py accepts the string "inf" precisely so a hand-written client can
   reach for null and a YAML-translated one can reach for "inf". */
export const UNLIMITED = null;

function wireLimit(mw) {
  return mw === UNLIMITED ? "inf" : mw;
}

/* ------------------------------------------------------------------ the seed
 *
 * web/data/case5.json is configs/w1.yaml restated as JSON, asserted equal to
 * it by tests/test_w2_editor.py. Fetched rather than inlined so there is one
 * copy of the scenario and Python can check it; a second hand-typed copy is
 * how the page ends up pricing a network the repo does not test.
 */
export async function fetchSeed() {
  const response = await fetch("data/case5.json");
  if (!response.ok) {
    throw new Error(`data/case5.json: server returned ${response.status}`);
  }
  return response.json();
}

export function stateFromSeed(seed) {
  const config = seed.config;
  return {
    /* Buses are an ORDERED list, not an object. Order is load-bearing: the
       engine takes buses[0] when a recorded slack is gone, and colour is
       assigned by identity in config order. */
    buses: config.network.buses.map((name) => ({
      name,
      x: seed.coords[name].x,
      y: seed.coords[name].y,
    })),
    branches: Object.fromEntries(
      Object.entries(config.network.branches).map(([name, spec]) => [
        name,
        {
          from: spec.from,
          to: spec.to,
          reactance_pu: spec.reactance_pu,
          limit_mw: spec.limit_mw === "inf" ? UNLIMITED : spec.limit_mw,
        },
      ]),
    ),
    fleet: structuredClone(config.fleet),
    bids: structuredClone(config.load.bids),
    shape: [...config.load.shape],
    slack: seed.slack,
    hour: seed.hour,
    /* Line-rating overrides, line -> MW. NOT a config edit: clear() takes
       limits as its own argument, so the slider moves a rating without
       rewriting the scenario the rating belongs to. */
    limits: {},
    /* The one market parameter the defaults policy reads. Data, never a
       constant here -- ERCOT's cap was $9000/MWh before 2021. */
    offerCap: seed.market.offer_cap_usd_per_mwh,
  };
}

/* ------------------------------------------------------- the defaults policy
 *
 * A DEFAULT IS A MARKET ASSUMPTION, NOT A UI DETAIL. Every one of these puts
 * a number into an LP that a visitor did not type, so each is written down
 * with the reason it is that number and not another.
 *
 *   new bus        No generator and no bid. A connected bus with neither
 *                  prices correctly and gets a real LMP -- CLAUDE.md lists
 *                  that under "not a bug, do not fix" -- so the honest
 *                  default is to add nothing the visitor did not ask for.
 *
 *   new branch     reactance 0.0300 pu, the same order as case5's six lines
 *                  (0.0064-0.0304), so a new line is comparable to the ones
 *                  it joins rather than a near-short or a near-open circuit.
 *                  Unlimited, because a rating invented by the editor would
 *                  manufacture congestion the visitor never asked for, and
 *                  congestion is the thing the whole site is about. Raising
 *                  it is a deliberate move on the slider.
 *
 *   new generator  $25/MWh and 100 MW. The cost sits between case5's
 *                  cheapest offer ($10 brighton) and its dearest ($40
 *                  sundance), so a new unit is neither always in merit nor
 *                  never in it -- either extreme would make adding a
 *                  generator look like it did nothing.
 *
 *   new bid        100 MW valued AT THE OFFER CAP, i.e. firm. The editor
 *                  emits only blocks, so new load must carry a price; the cap
 *                  outbids every generator and so reproduces inelastic load's
 *                  behaviour without inelastic load's infeasibility. Drop the
 *                  value below an LMP and the same bid becomes demand
 *                  response, which is the point of naming bids.
 */
export const DEFAULT_REACTANCE_PU = 0.03;
export const DEFAULT_GEN_COST_USD_PER_MWH = 25.0;
export const DEFAULT_GEN_PMAX_MW = 100.0;
export const DEFAULT_BID_PEAK_MW = 100.0;

export function defaultBranch(from, to) {
  return { from, to, reactance_pu: DEFAULT_REACTANCE_PU, limit_mw: UNLIMITED };
}

export function defaultGenerator(bus) {
  return {
    bus,
    cost_usd_per_mwh: DEFAULT_GEN_COST_USD_PER_MWH,
    pmax_mw: DEFAULT_GEN_PMAX_MW,
  };
}

export function defaultBid(bus, offerCap) {
  return { bus, peak_mw: DEFAULT_BID_PEAK_MW, value_usd_per_mwh: offerCap };
}

/* ------------------------------------------------------------- the emitters */

/* The config dict this state declares -- the same shape configs/*.yaml carry,
   because scenario_from_config reads both and one code path is the point. */
export function toConfig(state) {
  return {
    name: "web",
    network: {
      slack: state.slack,
      buses: state.buses.map((bus) => bus.name),
      branches: Object.fromEntries(
        Object.entries(state.branches).map(([name, br]) => [
          name,
          {
            from: br.from,
            to: br.to,
            reactance_pu: br.reactance_pu,
            limit_mw: wireLimit(br.limit_mw),
          },
        ]),
      ),
    },
    fleet: structuredClone(state.fleet),
    load: {
      source: "blocks",
      bids: structuredClone(state.bids),
      shape: [...state.shape],
    },
  };
}

/* clear()'s limits= argument, or null when no slider has been touched. Null
   rather than {} so an untouched editor posts the scenario's own ratings and
   nothing else -- an empty override and no override mean the same thing to
   the engine, and saying it one way keeps the posted body readable. */
export function toLimits(state) {
  const entries = Object.entries(state.limits);
  if (entries.length === 0) return null;
  return Object.fromEntries(entries.map(([line, mw]) => [line, wireLimit(mw)]));
}

/* --------------------------------------------------------- the bound check
 *
 * Mirrors src/api/bounds.py so the editor can refuse before it posts. This is
 * a COURTESY, not the defence: bounds.py is the defence, it rejects rather
 * than truncates, and it does not trust this file to have run. The codes are
 * the server's own, so one error surface (W2.2) renders both.
 *
 * Returns a list of {code, detail}; empty means the body is within the caps.
 * It does not say the scenario is valid -- scenario_from_config still refuses
 * a duplicate name, a zero reactance and a slack that is not a bus, and those
 * refusals are sentences written to be read, so they are displayed, not
 * pre-empted.
 */
export function checkBounds(state, caps) {
  const problems = [];
  const over = (n, cap, what) => {
    if (n > cap) {
      problems.push({
        code: `too_many_${what}`,
        detail: `${n} ${what} requested; the limit is ${cap}`,
      });
    }
  };
  over(state.buses.length, caps.max_buses, "buses");
  over(Object.keys(state.branches).length, caps.max_branches, "branches");
  over(Object.keys(state.fleet).length, caps.max_generators, "generators");
  over(Object.keys(state.bids).length, caps.max_bids, "bids");
  over(state.shape.length, caps.max_hours, "hours");

  const bytes = new TextEncoder().encode(
    JSON.stringify({ config: toConfig(state), slack: state.slack, limits: toLimits(state) }),
  ).length;
  if (bytes > caps.max_body_bytes) {
    problems.push({
      code: "body_too_large",
      detail: `request body is ${bytes} bytes; the limit is ${caps.max_body_bytes}`,
    });
  }
  return problems;
}
