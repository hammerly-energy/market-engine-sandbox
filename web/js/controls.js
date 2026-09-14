/* W2.4: the five levers that are not a drag.
 *
 *   line limit     -> state.limits[line], which is clear()'s limits= Argument
 *                     and not a config edit
 *   peak load      -> bid.peak_mw, one row per bus, and zero on that row
 *                     removes the bid rather than declaring a 0 MW one
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

import { bidNameFor, bidsAt, setBidPeak } from "./edits.js";
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

/* The track starts at one step, not at zero. A rating of 0 MW is refused by
   clear() -- it is Branch's rule, that a line able to carry nothing should be
   deleted rather than rated -- so a slider reaching it would put an error
   message at the end of a lever's travel. The engine's refusal stays as the
   check that catches this floor going missing; it is not the thing the
   visitor is meant to meet. */
const LIMIT_FLOOR_MW = LIMIT_STEP_MW;

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
  if (mw === UNLIMITED) return LIMIT_INF_POS;
  return Math.min(Math.max(mw, LIMIT_FLOOR_MW), LIMIT_CEILING_MW);
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

/* The current mount's pause, as a function, so that something which is not a
 * lever can stop playback without holding a reference to the levers. W3.10
 * gave the heatmap a click that picks an hour, and a pick that left the timer
 * running would move the cursor and then walk it straight off the hour the
 * visitor asked for.
 *
 * Module state for the same reason `transport` is: a structural edit throws
 * the old buttons away and mounts new ones, so a pause captured by a caller
 * would close over a button that is no longer on the page. Reset on every
 * mount, below.
 *
 * It clears the timer AND restores the button, which is why stopTransport is
 * not enough on its own -- a cleared timer under a button still reading
 * "Pause" is a control that lies about its own state.
 */
let pause = () => {};

export function pausePlayback() {
  pause();
}

const mw = (x) => `${x.toFixed(0)} MW`;
const usdPerMwh = (x) => `$${x.toFixed(2)}`;
const limitText = (pos) => (pos >= LIMIT_INF_POS ? "∞" : mw(pos));

/* --------------------------------------------------------------- the mount
 *
 * mountLevers(el, state, {onEdit}) -> sync()
 *
 *   onEdit()   state has changed in a way the Engine must answer. Re-solve.
 *
 * The hour is not here. It moved to mountHour at W3.11, because it stopped
 * being a row in this panel and became the Timeline's own control -- the one
 * lever whose track is a picture of what it indexes.
 *
 * sync() rewrites every readout from state, for the levers a lever moved --
 * nothing here reaches into another lever's value, so the sync exists for
 * undo (W2.7) and for the structural edits of W2.5, which rebuild instead.
 */
export function mountLevers(root, state, { onEdit }) {
  root.replaceChildren();
  const syncs = [];

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
      min: LIMIT_FLOOR_MW,
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

  /* ---- demand. A row per bus, and the row exists whether that bus has a
     bid or not: 0 MW is a bus with no demand, and raising the slider off zero
     declares one. Before this the group iterated state.bids, so A and E --
     the two buses case5 seeds no load at -- had no row at all and no way to
     grow one, which made "where load sits" a property of the seed rather than
     something a visitor could change.

     That reverses this block's earlier per-bid rule. The reasoning there was
     that two bids at one bus is a demand curve and not a collision, so a
     per-bus slider would have to pick one of them to move. It still would --
     so a bus carrying more than one bid keeps a row per bid and no creation,
     and the per-bus row is for the one-or-none case the editor can actually
     produce. The row is labelled with the bid's name, existing or not, so it
     names the object it declares.

     The value each bid places is NOT a lever here. Every bid the editor makes
     is firm, at the offer cap; dropping one below an LMP turns it into demand
     response, which is M9(a)'s figure and a config line, not a slider on this
     page. */
  const demand = group(
    "Demand Bids",
    "Peak MW per bid, scaled by the 24-hour shape. Zero is a bus with no " +
      "bid. Every bid is firm, at the offer cap.",
  );
  for (const bus of state.buses) {
    const here = bidsAt(state.bids, bus.name);

    /* Hand-written configs only: the editor makes at most one bid per bus.
       These rows move a bid that exists and never create or destroy one. */
    if (here.length > 1) {
      for (const [name, bid] of here) {
        const s = slider({
          name: `${name} (${bus.name})`,
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
      continue;
    }

    /* By name, not by object. The slider deletes the bid at zero and makes
       another with the same name on the way back up, so a closure over the
       object would be writing into a deleted one from the first step. */
    const name = bidNameFor(state, bus.name);
    const peak = () => Math.min(state.bids[name]?.peak_mw ?? 0, PEAK_MAX_MW);
    const s = slider({
      name: `${name} (${bus.name})`,
      min: 0,
      max: PEAK_MAX_MW,
      step: PEAK_STEP_MW,
      value: peak(),
      format: mw,
      onInput: (v) => {
        setBidPeak(state, bus.name, name, v);
        onEdit();
      },
    });
    demand.append(s.row);
    syncs.push(() => s.sync(peak()));
  }
  root.append(demand);

  return function sync() {
    for (const f of syncs) f();
  };
}

/* --------------------------------------------------------- the hour, W3.11
 *
 * mountHour(el, state, {onHour}) -> sync()
 *
 * The hour left the Levers panel and became the Timeline's own control. It
 * was always the odd one in that stack: the other six declare something the
 * engine must answer for, and this one walks an answer already in the
 * browser. In the Timeline it sits above the field it indexes, and the track
 * and the band are the same 24 hours at the same width, so the thumb is
 * literally over the hour it names.
 *
 * The transport, the pause rule and the sync contract are unchanged --
 * mountLevers returned a sync() and so does this. What changed is where the
 * row is mounted and that it no longer carries a readout: "Hour 19 of 24"
 * is printed in the Timeline's footer, once, beside the key.
 */
export function mountHour(root, state, { onHour }) {
  root.replaceChildren();
  stopTransport();
  pause = () => {};

  const lastHour = Math.max(state.shape.length, 1);

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
    /* No readout on this row. The Timeline prints the hour in its footer,
       where it sits beside the key rather than at the end of the track --
       and a number at the end of the track would shorten the track, which
       has to be exactly as wide as the band under it. */
    format: () => "",
    kind: "index",
    /* No ticks, and W2.7 gave this lever two encodings of "does not
       re-solve" -- a hollow thumb and ticks every six hours. The hollow
       thumb stays. The ticks are gone because the band directly beneath the
       track now breaks at the same three places, and it is the stronger
       mark of the two.

       They also could not be made to line up. A tick sits at the thumb
       CENTRE for that hour and a break sits at the BOUNDARY after it, and
       the thumb's travel is inset by half a thumb:

           tick, hour 6     (6-1)/23 of (W - 11.2px) + 5.6px  =  87.8px
           break, 6 | 7     6/24 of W                         =  97.5px
                                                  measured at W = 390px

       Ten pixels apart, on two marks a reader would take for one. */
    ticks: null,
    lead: play,
    onInput: (h) => {
      /* Taking the hour by hand stops the transport. Without this the timer
         overwrites the drag every 400 ms and the thumb fights the hand. The
         same rule applies to a click on the field, which is why pause is
         module state rather than a closure here. */
      pause();
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

  pause = () => setPlaying(false);

  root.append(hour.row);
  return function sync() {
    hour.sync(state.hour + 1);
  };
}
