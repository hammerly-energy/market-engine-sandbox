/* W3.6: line flows against limits.
 *
 * One row per line, all six drawn on ONE shared MW axis:
 *
 *          |         |                        Flow (MW)  Loading (%)   mu
 *   A → B  |     ├───┼━━━━━━━━┤                   250.0        100    -9.34
 *   A → D  |         ┼━━━━━                       159.7          —       —
 *   A → E  |  ━━━━━━━┼                           -355.4          —       —
 *   B → C  |         ┼━                              7.0          —       —
 *   C → D  |      ━━━┼                            -75.7          —       —
 *   D → E  |    ├━━━━┼────┤                      -240.0        100    47.53
 *       -400 MW      0      400 MW
 *
 * The BAR is the flow, from zero, on a scale shared by every line. The TICKS
 * are that line's rating in each direction. A bar that reaches its tick is a
 * line at its limit, and a line with no ticks has no rating.
 *
 * That is the whole reason the axis is shared rather than each track being
 * the line's own +/- rating. A per-line track has no room for an unrated
 * line: f / inf = 0 and the bar vanishes, so a branch carrying 355 MW drew
 * the same as one sitting idle. On a shared MW axis an unrated line is simply
 * the longest bar on the panel, and the absence of ticks says what is missing
 * -- the rating -- instead of pretending the flow is.
 *
 * A line at its rating is therefore stated twice, from two independent
 * routes: the bar meets its tick, which is the primal, and mu is non-zero,
 * which is the dual. The panel draws each from its own field and derives
 * neither from the other.
 *
 * Direction is position: a bar left of zero runs to -> from. Hue repeats it
 * and is the half that survives neither grayscale nor colour blindness, so
 * position is the one carrying it (see scales.js for the measurement).
 *
 * The boundary rule holds. Flow, rating, loading and mu are all fields of the
 * clear() return; this file turns MW into a percentage of a track, which is
 * geometry, and never divides a flow by a rating.
 */

import { flowDomain, flowInk, FLOW_NEG, FLOW_POS, FLOW_ZERO } from "./scales.js";
import { usd } from "./render.js";

/* A dual this small is a line that is not binding. The same tolerance
   binding_lines() uses in clearing.py, so the panel and the engine agree on
   which lines are priced. */
const MU_TOL = 1e-9;

function cell(text, cls) {
  const el = document.createElement("span");
  el.className = cls;
  el.textContent = text;
  return el;
}

/* Half the track is the domain, so a value maps to a percentage either side
   of the centre. Geometry, not arithmetic on a price. */
const at = (mw, domain) => 50 + (mw / domain) * 50;

function header() {
  const row = document.createElement("div");
  row.className = "flow-row flow-head";
  row.append(
    cell("Line", "flow-name"),
    /* The bar is the flow and the ticks are the rating, so the column is
       named for both. It carries the MW once, for the axis under it: at this
       panel's width the axis ends could not hold "−400 MW" without wrapping
       into the legend below them. */
    cell("Flow against rating (MW)", "flow-track-head"),
    cell("Flow (MW)", "flow-num"),
    cell("Loading (%)", "flow-num"),
    cell("μ ($/MWh)", "flow-num"),
  );
  return row;
}

function row(name, cleared, hour, branches, domain) {
  const el = document.createElement("div");
  el.className = "flow-row";

  /* The endpoints are the label and the whole label. "A → B" says which way
     positive runs without a second column to explain it, and the branch name
     it replaces is already on the wire it describes, over on the map.

     Two branches between the same pair of buses are physical and legal, and
     they draw two rows reading "A → B". They are told apart by their flows,
     which differ, and by the tooltip, which names each -- the same trade the
     map makes when it bows parallel branches apart rather than labelling
     them twice. */
  const br = branches[name];
  const label = document.createElement("span");
  label.className = "flow-name";
  label.textContent = br ? `${br.from} → ${br.to}` : name;

  const track = document.createElement("div");
  track.className = "flow-track";

  const f = cleared.flows[name];
  const limit = cleared.limits[name];

  /* A line the last answer does not carry: connected since the solve, or gone
     from it. Named with no bar, so the row count matches the map. */
  if (!f) {
    el.append(label, track, cell("—", "flow-num"), cell("—", "flow-num"),
              cell("—", "flow-num"));
    return el;
  }

  const mw = f[hour];
  const x = cleared.loading[name][hour];
  const mu = cleared.mu[name][hour];
  const priced = Math.abs(mu) > MU_TOL;

  /* The rating, both ways, as ticks. Drawn before the bar so a binding bar
     ends on its tick rather than under it. A line with no rating gets none,
     and that absence is the panel's statement that it can never bind. */
  if (limit !== null) {
    for (const side of [-1, 1]) {
      const tick = document.createElement("div");
      tick.className = priced ? "flow-tick binding" : "flow-tick";
      tick.style.left = `${at(side * limit, domain)}%`;
      track.append(tick);
    }
  }

  const zero = document.createElement("div");
  zero.className = "flow-zero";
  zero.style.left = "50%";

  const bar = document.createElement("div");
  bar.className = "flow-bar";
  bar.style.left = `${at(Math.min(mw, 0), domain)}%`;
  bar.style.width = `${(Math.abs(mw) / domain) * 50}%`;
  bar.style.background = flowInk(mw);

  track.append(bar, zero);

  el.append(
    label,
    track,
    cell(mw.toFixed(1), "flow-num"),
    /* Unsigned: the sign is on the axis, twice, as the side of zero the bar
       falls on and as its hue. A third statement of it here would be a
       percentage that looks like it could exceed 100. */
    cell(limit === null ? "—" : (Math.abs(x) * 100).toFixed(0), "flow-num"),
    /* The dual, not a magnitude: its sign says which limit the line is
       holding at, positive at the lower and negative at the upper. An
       unbinding line has no price for its capacity and gets a dash rather
       than a zero, which would read as a measurement. */
    cell(priced ? usd(mu) : "—", "flow-num"),
  );

  /* Which of the two limits is holding, taken from the sign of the FLOW and
     not from the sign of mu. Both answer it -- that is the point of the
     caption -- but reading it off the primal leaves the dual's sign as
     something the reader can check against this rather than something the
     browser asserted from it. */
  el.title =
    `${name}: flow ${mw.toFixed(4)} MW` +
    (limit === null
      ? ", no rating, so it can never bind"
      : `, rating ${limit.toFixed(1)} MW, loading ${(x * 100).toFixed(2)}%`) +
    (priced
      ? /* The magnitude, because a saving is positive whichever limit is
           holding and mu is not: AB rated 150 returns mu = -39.3292 and
           raising it 1 MW saves $39.33. The signed number is in the column,
           where the caption says what its sign means. Abs is a formatting of
           a returned field, as the loading column above already is. */
        `\nAt its ${mw < 0 ? "lower" : "upper"} limit: one more MW of rating ` +
        `is worth $${Math.abs(mu).toFixed(4)}/MWh`
      : "\nNot binding: μ = 0, so this line adds nothing to any LMP");

  return el;
}

/* The axis, under the tracks and in their column, so its ends land on the
 * ends of every track.
 *
 * Each label is pinned to the position it names -- 0%, 50%, 100% -- rather
 * than laid out by a space-between flex. Flex distributes the LEFTOVER space
 * between three labels of different widths, so "0" landed wherever seven
 * characters of minus sign and eight of plus happened to leave it, and not on
 * the zero line every bar is measured from. It was a pixel or two out, which
 * is exactly the kind of thing a reader sees without being able to name.
 *
 * The ends are anchored rather than centred on their ticks: centring would
 * push half of "−400 MW" into the line names to its left. The zero is
 * centred, because that one has to sit on the rule.
 */
function axis(domain) {
  const wrap = document.createElement("div");
  wrap.className = "flow-row flow-axis-row";

  const ax = document.createElement("div");
  ax.className = "flow-axis";
  for (const [text, cls] of [
    [`−${domain}`, "flow-axis-lo"],
    ["0", "flow-axis-mid"],
    [`+${domain}`, "flow-axis-hi"],
  ]) {
    ax.append(cell(text, cls));
  }

  wrap.append(cell("", "flow-name"), ax, cell("", ""), cell("", ""), cell("", ""));
  return wrap;
}

/* The key. Three swatches rather than a gradient, because the scale is three
   colours and a gradient would offer a reader intermediate values that do not
   exist. Built from the same constants that ink the bars. */
function legend() {
  const wrap = document.createElement("div");
  wrap.className = "flow-legend";

  for (const [ink, text] of [
    [FLOW_NEG, "to → from"],
    [FLOW_ZERO, "idle"],
    [FLOW_POS, "from → to"],
  ]) {
    const item = document.createElement("span");
    item.className = "flow-key";
    const sw = document.createElement("span");
    sw.className = "flow-swatch";
    sw.style.background = ink;
    item.append(sw, cell(text, ""));
    wrap.append(item);
  }

  const says = document.createElement("p");
  says.className = "flow-ramp-note";
  says.textContent =
    "Ticks are the rating. A bar reaching its tick is a line at its limit. " +
    "The same colours ink the map.";
  wrap.append(says);
  return wrap;
}

export function renderFlows(el, cleared, hour, branches) {
  el.replaceChildren();

  if (!cleared.lines.length) {
    el.append(cell("No line in the last answer.", "note"));
    return;
  }

  const domain = flowDomain(cleared);

  /* One group per island when a cut has made more than one, because a line
     belongs to exactly one market and its rent is settled in that market's
     ledger. island_lines is the engine's own split, not a re-derivation. */
  const homes = Object.keys(cleared.island_lines);
  const many = homes.filter((h) => cleared.island_lines[h].length).length > 1;

  for (const home of homes) {
    const lines = cleared.island_lines[home];
    if (!lines.length) continue;

    const group = document.createElement("div");
    group.className = "flow-group";

    if (many) {
      const head = document.createElement("p");
      head.className = "flow-island";
      head.textContent = `Island ${home}`;
      group.append(head);
    }

    group.append(header());
    for (const name of lines) {
      group.append(row(name, cleared, hour, branches, domain));
    }
    group.append(axis(domain));
    el.append(group);
  }

  el.append(legend());
}
