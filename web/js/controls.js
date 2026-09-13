/* W2.4: the five levers that are not a drag.
 *
 *   line limit     -> state.limits[line], which is clear()'s limits= Argument
 *                     and not a config edit
 *   peak load      -> bid.peak_mw
 *   generator pmax -> gen.pmax_mw
 *   generator cost -> gen.cost_usd_per_mwh
 *   hour 1-24      -> state.hour, which does not re-solve
 *
 * and, added at W2.6, the sixth:
 *
 *   slack bus      -> state.slack, a dropdown over the bus list, posted
 *                     explicitly on every request
 *
 * The hour is the one that is different. clear() returns the whole day -- every series is one array per name aligned
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
 * The sliders are not debounced. Dragging one fires a solve per step and the
 * coalescing in api.js drops the stale answers; the price flicker at a
 * degenerate breakpoint survives, because it is the most honest thing this
 * site can show (CLAUDE.md, "Degeneracy under a moving slider").
 */

import { UNLIMITED } from "./state.js";

/* ----------------------------------------------------------- slider domains
 *
 * A domain is a market assumption, the same way a default is, so each one is
 * written down with the reason it is that number. Fixed, never rescaled to
 * the current state: a slider whose end moved when the scenario moved would
 * make the same hand position mean two different MW, which is the legend trap
 * arriving through the geometry instead.
 */

/* Line ratings. case5's whole firm peak is 1000 MW (300 + 300 + 400), so a
   line rated at the ceiling cannot bind on the seeded case, and the interval
   below it is where every interesting rating lives -- the DE line binds at
   240. The last notch is unlimited, literally: it writes null, not a big
   number, because "inf" is what the scenario says and a 1000 MW line that
   happens never to bind is a different claim from a line with no rating. */
const LIMIT_STEP_MW = 5;
const LIMIT_CEILING_MW = 1000;
const LIMIT_INF_POS = LIMIT_CEILING_MW + LIMIT_STEP_MW;

/* Generator capacity. case5's largest unit is E1 at 600 MW; the top of
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
function slider({
  name,
  min,
  max,
  step,
  value,
  format,
  onInput,
  kind = "edit",
  ticks = null,
  lead = null,
}) {
  const row = el("div", { class: "lever", "data-kind": kind });

  /* `lead` puts an element in the name column instead of the name. Only the
     hour uses it, to seat its transport where the label would otherwise
     repeat the legend directly above it. The input keeps its aria-label
     either way, so the control is still named without the <label>. */
  /* W3.2 took the identity dot off these rows. It coloured a lever by its
     bus, and a bus no longer has a colour of its own -- the ring on the map
     is its price. Every row already names its bus in the label. */
  const label = el(lead ? "span" : "label", { class: "lever-name" });
  if (lead) label.append(lead);
  else label.append(document.createTextNode(name));

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

  input.id = `lever-${name.replace(/\W+/g, "-")}`;
  if (!lead) label.setAttribute("for", input.id);

  /* The rail, and under it the ticks if this lever has any. A tick is a scale
     mark, not a control: aria-hidden, and pointer-events: none in style.css,
     where the half-thumb inset its position is measured against also lives.

         left = (v - min) / (max - min)

     of the inset rail, which is the thumb centre's own travel. */
  const scale = el("div", { class: "lever-scale" });
  scale.append(input);
  if (ticks && ticks.length) {
    const rail = el("div", { class: "lever-ticks", "aria-hidden": "true" });
    for (const v of ticks) {
      const tick = el("span");
      tick.style.left = `${((v - min) / (max - min)) * 100}%`;
      rail.append(tick);
    }
    scale.append(rail);
  }

  row.append(label, scale, readout);

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

/* ----------------------------------------------------------- the transport
 *
 * Play steps the hour through the day. It posts nothing -- it is the hour
 * slider moved on a timer, and the hour indexes arrays the last response
 * already carried. Solving each step instead would re-ask a question that
 * response answered, and at a degenerate breakpoint the second answer can
 * differ from the first (trap 3) with nothing on screen to explain it.
 *
 *     24 steps x 400 ms = 9.6 s a pass
 *
 * It loops, and it starts stopped: nothing on this page animates on load.
 * Motion here is continuity, not decoration (CLAUDE.md, Interactive figure
 * register).
 *
 * The timer is module state and is cleared at the top of every mount. A
 * structural edit rebuilds the levers, and an interval left running over that
 * rebuild would go on writing state.hour through a closure over levers that
 * were thrown away.
 */
const HOUR_STEP_MS = 400;
let transport = null;

function stopTransport() {
  if (transport !== null) clearInterval(transport);
  transport = null;
}

const mw = (x) => `${x.toFixed(0)} MW`;
const usdPerMwh = (x) => `$${x.toFixed(2)}`;
const limitText = (pos) => (pos >= LIMIT_INF_POS ? "∞" : mw(pos));

/* --------------------------------------------------------------- the mount
 *
 * mountLevers(el, state, {onEdit, onHour}) -> sync()
 *
 *   onEdit()   state has changed in a way the Engine must answer. Re-solve.
 *   onHour()   state has changed in a way the Response already answers.
 *              Re-read the arrays that are already here. No post.
 *
 * sync() rewrites every readout from state, for the levers a lever moved --
 * nothing here reaches into another lever's value, so the sync exists for
 * undo (W2.7) and for the structural edits of W2.5, which rebuild instead.
 */
export function mountLevers(root, state, { onEdit, onHour }) {
  root.replaceChildren();
  stopTransport();
  const syncs = [];

  /* ---- the hour. First, because it is the one that does not re-solve. */
  const hours = group(
    "Hour",
    "Indexes the day already here. Playing posts nothing.",
  );
  const lastHour = Math.max(state.shape.length, 1);

  /* Play, in the name column to the left of the rail. The name it displaces
     is "Hour", which the legend directly above already says. */
  const play = el("button", {
    type: "button",
    class: "transport",
    "aria-pressed": "false",
    "aria-label": "Play the day, one hour at a time",
  }, "Play");
  play.disabled = state.shape.length < 2;

  const hour = slider({
    name: "Hour",
    min: 1,
    max: lastHour,
    step: 1,
    value: state.hour + 1,
    format: (h) => `${h} of ${state.shape.length}`,
    /* W2.7. The lever that does not re-solve says so in its geometry: a hollow
       thumb, and ticks every six hours. Both are in style.css. */
    kind: "index",
    ticks: Array.from(
      { length: Math.floor(lastHour / 6) },
      (_, i) => (i + 1) * 6,
    ),
    lead: play,
    onInput: (h) => {
      state.hour = h - 1;
      onHour();
    },
  });
  const showHour = () => {
    hour.sync(state.hour + 1);
    onHour();
  };

  const setPlaying = (on) => {
    stopTransport();
    play.setAttribute("aria-pressed", String(on));
    play.textContent = on ? "Pause" : "Play";
    if (!on) return;
    transport = setInterval(() => {
      state.hour = (state.hour + 1) % state.shape.length;
      showHour();
    }, HOUR_STEP_MS);
  };

  play.addEventListener("click", () => {
    setPlaying(play.getAttribute("aria-pressed") !== "true");
  });

  hours.append(hour.row);
  syncs.push(() => hour.sync(state.hour + 1));
  root.append(hours);

  /* ---- the slack bus (W2.6).
   *
   * A dropdown over the bus list, posted explicitly on every request. It
   * re-solves, and what it moves is worth being exact about, because the
   * obvious wrong expectation is that it moves prices:
   *
   *     λ moves.                    λ is the LMP at the slack.
   *     the congestion split moves. PTDF[l, slack] = 0 by construction.
   *     no LMP moves.               The two changes cancel.
   *     no payment, revenue or rent moves either.
   *
   * Measured on case5, slack D → A → E: λ moves $30 and no LMP moves. Equal
   * to float64 debris, not bitwise -- a different slack is a different PTDF
   * and so a different LP, which leaves ~1.7e-13 on an LMP and ~9.8e-11 on a
   * payment (CLAUDE.md, trap 2). No view on this page shows that many digits,
   * so on screen the prices do not move.
   *
   * The editor owns keeping this in step with its bus list: removeBus moves
   * the slack to the first remaining bus, the same rule the engine's own
   * fallback follows. The engine's refusal of a slack that is not a bus is
   * kept, and it is the check that catches this failing (CLAUDE.md, W2.6).
   */
  const origin = group(
    "Slack Bus",
    "An accounting origin. Moving it moves λ and the energy/congestion " +
      "split, and no LMP, payment or settlement figure.",
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

  /* ---- line ratings. An Override, not a config edit: clear() takes limits
     as its own argument, so moving a rating does not rewrite the scenario the
     rating belongs to, and dropping the override restores it exactly. */
  const lines = group(
    "Line Ratings",
    "An override passed alongside the scenario, not an edit to it. ∞ is an " +
      "unrated line, not a very large rating.",
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

  /* ---- generators: capacity and offer, two levers on one unit.
   *
   * The label is the name alone. It used to carry the bus after it, because
   * the place names the fleet had before W3.7 said nothing about where a
   * unit was. A1 does, so the suffix became the same letter twice. */
  const fleet = group(
    "Generators",
    "Capacity and offer per unit. No unit commitment, so a unit may run at " +
      "any level up to its capacity.",
  );
  for (const [name, gen] of Object.entries(state.fleet)) {
    const cap = slider({
      name: `${name} capacity`,
      min: 0,
      max: PMAX_MAX_MW,
      step: PMAX_STEP_MW,
      value: Math.min(gen.pmax_mw, PMAX_MAX_MW),
      format: mw,
      onInput: (v) => {
        gen.pmax_mw = v;
        onEdit();
      },
    });
    const cost = slider({
      name: `${name} offer`,
      min: 0,
      max: COST_MAX_USD,
      step: COST_STEP_USD,
      value: Math.min(gen.cost_usd_per_mwh, COST_MAX_USD),
      format: usdPerMwh,
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

  /* ---- demand. Per bid, not per bus, even though CLAUDE.md's lever list
     says "peak load per bus" -- because two bids at one bus is a demand curve
     and not a collision, and a per-bus slider would have to pick one of them
     to move or split the move between them. Both are inventions. The bid is
     the named object the engine prices, so the bid is what carries a lever.

     The value each bid places is NOT a lever here. Every seeded bid is firm,
     at the offer cap; dropping one below an LMP turns it into demand response,
     which is M9(a)'s figure and a config line, not a slider on this page. */
  const demand = group(
    "Demand Bids",
    "Peak MW per bid, scaled by the 24-hour shape. Every bid is firm, at " +
      "the offer cap.",
  );
  for (const [name, bid] of Object.entries(state.bids)) {
    const s = slider({
      name: `${name} (${bid.bus})`,
      min: 0,
      max: PEAK_MAX_MW,
      step: PEAK_STEP_MW,
      value: Math.min(bid.peak_mw, PEAK_MAX_MW),
      format: mw,
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
