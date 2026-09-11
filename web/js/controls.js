/* W2.4: the five levers that are not a drag.
 *
 *   line limit     -> state.limits[line], which is clear()'s limits= ARGUMENT
 *                     and not a config edit
 *   peak load      -> bid.peak_mw
 *   generator pmax -> gen.pmax_mw
 *   generator cost -> gen.cost_usd_per_mwh
 *   hour 1-24      -> state.hour, WHICH DOES NOT RE-SOLVE
 *
 * and, added at W2.6, the sixth:
 *
 *   slack bus      -> state.slack, a dropdown over the bus list, posted
 *                     explicitly on every request
 *
 * THE HOUR IS THE ONE THAT IS DIFFERENT AND IT IS THE POINT OF THIS PHASE.
 * clear() returns the whole day -- every series is one array per name aligned
 * to `hours` -- so moving the hour indexes arrays that are already in the
 * browser. Posting a solve to look at hour 19 of a day already on the page
 * would be a second answer to a question already answered, and the two could
 * disagree at a degenerate breakpoint (trap 3) for no reason a reader could
 * see. So the hour calls onHour and the other four call onEdit, and this
 * module is where that distinction is enforced.
 *
 * No market arithmetic here. A lever writes a declaration into editor state;
 * every number it reads back comes from a clear() return. The readout beside
 * a slider is the slider's own position formatted -- what that position did
 * to a price is the engine's answer, printed elsewhere.
 *
 * THE SLIDERS ARE NOT DEBOUNCED. Dragging one fires a solve per step and the
 * coalescing in api.js drops the stale answers; the price flicker at a
 * degenerate breakpoint survives, because it is the most honest thing this
 * site can show (CLAUDE.md, "Degeneracy under a moving slider").
 */

import { UNLIMITED } from "./state.js";

/* ----------------------------------------------------------- slider domains
 *
 * A DOMAIN IS A MARKET ASSUMPTION, the same way a default is, so each one is
 * written down with the reason it is that number. Fixed, never rescaled to
 * the current state: a slider whose end moved when the scenario moved would
 * make the same hand position mean two different MW, which is the legend trap
 * arriving through the geometry instead.
 */

/* Line ratings. case5's whole firm peak is 1000 MW (300 + 300 + 400), so a
   line rated at the ceiling cannot bind on the seeded case, and the interval
   below it is where every interesting rating lives -- the DE line binds at
   240. The LAST NOTCH IS UNLIMITED, literally: it writes null, not a big
   number, because "inf" is what the scenario says and a 1000 MW line that
   happens never to bind is a different claim from a line with no rating. */
const LIMIT_STEP_MW = 5;
const LIMIT_CEILING_MW = 1000;
const LIMIT_INF_POS = LIMIT_CEILING_MW + LIMIT_STEP_MW;

/* Generator capacity. case5's largest unit is brighton at 600 MW; the top of
   the range sits above it so the biggest unit is not pinned at the end. */
const PMAX_MAX_MW = 700;
const PMAX_STEP_MW = 10;

/* Marginal cost. case5's offers run $10-40/MWh and the range reaches $100 so
   a unit can be pushed out of merit and back. It does NOT reach the $5000
   offer cap: the cap is what firm load bids, and a generator offering at the
   cap would price the market at scarcity in every hour, which is a scenario
   to write in a config rather than to reach by dragging past everything
   interesting. It does not go below zero either -- negative offers are real
   (a unit paid to run) and they are not in this fleet. */
const COST_MAX_USD = 100;
const COST_STEP_USD = 0.5;

/* Demand. Same ceiling as capacity, so a bid and a unit are read on the same
   scale and "is there enough generation" is a comparison the eye can make. */
const PEAK_MAX_MW = 700;
const PEAK_STEP_MW = 10;

/* ----------------------------------------------------------------- widgets */

function el(tag, attrs = {}, text = null) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else e.setAttribute(k, String(v));
  }
  if (text !== null) e.textContent = text;
  return e;
}

/* One labelled slider. Returns {row, sync} -- sync() rewrites the readout
   from state WITHOUT touching the input, because rebuilding an input under a
   dragging thumb drops the drag. */
function slider({ name, min, max, step, value, format, onInput, swatch = null }) {
  const row = el("div", { class: "lever" });

  const label = el("label", { class: "lever-name" });
  if (swatch) {
    const dot = el("span", { class: "swatch" });
    dot.style.background = swatch;
    label.append(dot);
  }
  label.append(document.createTextNode(name));

  const input = el("input", {
    type: "range",
    min,
    max,
    step,
    value,
    "aria-label": name,
  });
  const readout = el("output", { class: "lever-value" }, format(value));

  input.addEventListener("input", () => {
    const pos = Number(input.value);
    readout.textContent = format(pos);
    onInput(pos);
  });

  label.setAttribute("for", (input.id = `lever-${name.replace(/\W+/g, "-")}`));
  row.append(label, input, readout);

  return {
    row,
    sync(pos) {
      if (Number(input.value) !== pos) input.value = String(pos);
      readout.textContent = format(pos);
    },
  };
}

/* One labelled chooser. Same row geometry as a slider, and the same sync
   contract -- sync() rewrites the selection from state without rebuilding the
   element, because a <select> rebuilt under an open popup closes it. */
function chooser({ name, options, value, onChange }) {
  const row = el("div", { class: "lever" });
  const label = el("label", { class: "lever-name" }, name);
  const select = el("select", { "aria-label": name });

  const fill = (chosen) => {
    select.replaceChildren();
    /* A value that is not in the list still gets an option, disabled and
       selected. Only reachable with no buses left, where there is nothing
       honest to move the slack to -- and a select that silently displayed
       some other bus would be the editor lying about what it will post. */
    if (chosen !== null && !options.includes(chosen)) {
      const orphan = el("option", { value: chosen, disabled: "" }, chosen);
      select.append(orphan);
    }
    for (const option of options) select.append(el("option", { value: option }, option));
    select.value = chosen ?? "";
    select.disabled = options.length === 0;
  };
  fill(value);

  select.addEventListener("change", () => onChange(select.value));
  label.setAttribute("for", (select.id = `lever-${name.replace(/\W+/g, "-")}`));
  row.append(label, select);

  return {
    row,
    sync(chosen) {
      if (select.value !== chosen) fill(chosen);
    },
  };
}

function group(title, note = null) {
  const box = el("fieldset", { class: "lever-group" });
  box.append(el("legend", {}, title));
  if (note) box.append(el("p", { class: "note" }, note));
  return box;
}

/* ------------------------------------------------------------ the encodings
 *
 * Slider position <-> the number in editor state. Only the line rating needs
 * one, because it carries a value -- unlimited -- that is not on the number
 * line at all.
 */

function limitToPos(mw) {
  return mw === UNLIMITED ? LIMIT_INF_POS : Math.min(mw, LIMIT_CEILING_MW);
}

function posToLimit(pos) {
  return pos >= LIMIT_INF_POS ? UNLIMITED : pos;
}

const mw = (x) => `${x.toFixed(0)} MW`;
const usdPerMwh = (x) => `$${x.toFixed(2)}`;
const limitText = (pos) => (pos >= LIMIT_INF_POS ? "∞" : mw(pos));

/* --------------------------------------------------------------- the mount
 *
 * mountLevers(el, state, {onEdit, onHour}) -> sync()
 *
 *   onEdit()   state has changed in a way the ENGINE must answer. Re-solve.
 *   onHour()   state has changed in a way the RESPONSE already answers.
 *              Re-read the arrays that are already here. No post.
 *
 * sync() rewrites every readout from state, for the levers a lever moved --
 * nothing here reaches into another lever's value, so the sync exists for
 * undo (W2.7) and for the structural edits of W2.5, which rebuild instead.
 */
export function mountLevers(root, state, { onEdit, onHour, hueFor }) {
  root.replaceChildren();
  const syncs = [];

  /* ---- the hour. First, because it is the one that does not re-solve. */
  const hours = group(
    "Hour",
    "Indexes the day the last solve returned. It does not post a solve — the " +
      "day comes back whole.",
  );
  const hour = slider({
    name: "Hour",
    min: 1,
    max: Math.max(state.shape.length, 1),
    step: 1,
    value: state.hour + 1,
    format: (h) => `${h} of ${state.shape.length}`,
    onInput: (h) => {
      state.hour = h - 1;
      onHour();
    },
  });
  hours.append(hour.row);
  syncs.push(() => hour.sync(state.hour + 1));
  root.append(hours);

  /* ---- the slack bus (W2.6).
   *
   * A DROPDOWN OVER THE BUS LIST, POSTED EXPLICITLY ON EVERY REQUEST. It
   * re-solves, and what it moves is worth being exact about, because the
   * obvious wrong expectation is that it moves prices:
   *
   *     λ moves.                    λ IS the LMP at the slack.
   *     the congestion split moves. PTDF[l, slack] = 0 by construction.
   *     NO LMP MOVES. Not one.      The two changes cancel exactly.
   *     no payment, revenue or rent moves either.
   *
   * Measured on case5, slack D → A → E: λ moves $30 and every LMP is
   * bit-identical (CLAUDE.md, trap 2). So this lever is the one place the
   * site can show that the slack is an accounting origin rather than a
   * modelling assumption -- and a page that showed prices sliding when it
   * moved would have a bug in it, not a feature.
   *
   * The editor OWNS keeping this in step with its bus list: removeBus moves
   * the slack to the first remaining bus, the same rule the engine's own
   * fallback follows. The engine's refusal of a slack that is not a bus is
   * kept, and it is the check that catches this failing (CLAUDE.md, W2.6).
   */
  const origin = group(
    "Slack Bus",
    "An accounting origin, not a modelling assumption. Moving it moves λ and " +
      "the split between energy and congestion; it moves no LMP, no payment " +
      "and no settlement figure at all. The ring on the map follows it.",
  );
  const slack = chooser({
    name: "Slack",
    options: state.buses.map((bus) => bus.name),
    value: state.slack,
    onChange: (name) => {
      state.slack = name;
      onEdit();
    },
  });
  origin.append(slack.row);
  syncs.push(() => slack.sync(state.slack));
  root.append(origin);

  /* ---- line ratings. An OVERRIDE, not a config edit: clear() takes limits
     as its own argument, so moving a rating does not rewrite the scenario the
     rating belongs to, and dropping the override restores it exactly. */
  const lines = group(
    "Line Ratings",
    "An override passed to the engine alongside the scenario, not an edit to " +
      "it. ∞ is an unrated line, which is what the scenario says — not a " +
      "rating large enough never to bind.",
  );
  for (const [line, branch] of Object.entries(state.branches)) {
    const s = slider({
      name: line,
      min: 0,
      max: LIMIT_INF_POS,
      step: LIMIT_STEP_MW,
      value: limitToPos(state.limits[line] ?? branch.limit_mw),
      format: limitText,
      onInput: (pos) => {
        state.limits[line] = posToLimit(pos);
        onEdit();
      },
    });
    lines.append(s.row);
    syncs.push(() => s.sync(limitToPos(state.limits[line] ?? branch.limit_mw)));
  }
  root.append(lines);

  /* ---- generators: capacity and offer, two levers on one unit. */
  const busIndex = new Map(state.buses.map((b, i) => [b.name, i]));
  const fleet = group(
    "Generators",
    "Capacity and the offer each unit is dispatched against. Offers are " +
      "cost-based; there is no unit commitment, so a unit may run at any " +
      "level between zero and its capacity.",
  );
  for (const [name, gen] of Object.entries(state.fleet)) {
    const hue = hueFor(busIndex.get(gen.bus) ?? -1);
    const cap = slider({
      name: `${name} (${gen.bus}) capacity`,
      min: 0,
      max: PMAX_MAX_MW,
      step: PMAX_STEP_MW,
      value: Math.min(gen.pmax_mw, PMAX_MAX_MW),
      format: mw,
      swatch: hue,
      onInput: (v) => {
        gen.pmax_mw = v;
        onEdit();
      },
    });
    const cost = slider({
      name: `${name} (${gen.bus}) offer`,
      min: 0,
      max: COST_MAX_USD,
      step: COST_STEP_USD,
      value: Math.min(gen.cost_usd_per_mwh, COST_MAX_USD),
      format: usdPerMwh,
      swatch: hue,
      onInput: (v) => {
        gen.cost_usd_per_mwh = v;
        onEdit();
      },
    });
    fleet.append(cap.row, cost.row);
    syncs.push(() => cap.sync(Math.min(gen.pmax_mw, PMAX_MAX_MW)));
    syncs.push(() => cost.sync(Math.min(gen.cost_usd_per_mwh, COST_MAX_USD)));
  }
  root.append(fleet);

  /* ---- demand. PER BID, not per bus, even though CLAUDE.md's lever list
     says "peak load per bus" -- because two bids at one bus is a demand curve
     and not a collision, and a per-bus slider would have to pick one of them
     to move or split the move between them. Both are inventions. The bid is
     the named object the engine prices, so the bid is what carries a lever.

     The value each bid places is NOT a lever here. Every seeded bid is firm,
     at the offer cap; dropping one below an LMP turns it into demand response,
     which is M9(a)'s figure and a config line, not a slider on this page. */
  const demand = group(
    "Demand Bids",
    "Peak MW per named bid, scaled by the 24-hour shape. Every bid is firm — " +
      "valued at the offer cap — so it is served unless the network cannot " +
      "reach it.",
  );
  for (const [name, bid] of Object.entries(state.bids)) {
    const s = slider({
      name: `${name} (${bid.bus})`,
      min: 0,
      max: PEAK_MAX_MW,
      step: PEAK_STEP_MW,
      value: Math.min(bid.peak_mw, PEAK_MAX_MW),
      format: mw,
      swatch: hueFor(busIndex.get(bid.bus) ?? -1),
      onInput: (v) => {
        bid.peak_mw = v;
        onEdit();
      },
    });
    demand.append(s.row);
    syncs.push(() => s.sync(Math.min(bid.peak_mw, PEAK_MAX_MW)));
  }
  root.append(demand);

  return function sync() {
    for (const f of syncs) f();
  };
}
