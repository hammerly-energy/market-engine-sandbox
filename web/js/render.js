/* W2.3: enough feedback to prove a lever worked, and no more.
 *
 * Three readouts and a picture:
 *
 *     the map        buses and branches, drawn from editor state, because
 *                    coordinates live there and never cross the wire. It
 *                    shows topology and identity -- not price. Colouring a
 *                    bus by its LMP is W3's network view, and building it
 *                    here would make a transport bug look like a colour bug.
 *
 *     LMP per bus    one number per bus, for the hour the editor is on.
 *     lambda         one per island, keyed by the island's slack.
 *     the residual   the claim the whole repo rests on, displayed.
 *
 * The boundary rule, in this file: every number below is a
 * field of the clear() return, rounded to a string. This module never adds
 * lambda to a congestion component, never multiplies mu by a flow and never
 * computes a residual -- the residual is Read from settlement, because a
 * residual this file computed would be a second implementation of the LMP
 * assembly and would agree with itself no matter how wrong the engine was.
 *
 * What this file does compute is geometry: where a disc sits, which way a
 * parallel branch bows. That is not market arithmetic, and none of it reaches
 * a number on the wire.
 *
 * W2.5 adds the marks the editing grammar needs and nothing else. Every bus,
 * branch and generator becomes a focusable element carrying its own name in a
 * data- attribute, with a transparent shape over it for pointer comfort -- so
 * grammar.js's hit test is `closest()` and not a distance search. Generators
 * appear on the map for the first time here, because Remove is armed and then
 * clicked and a unit with no mark could only be removed by a second grammar.
 * The colouring is unchanged and is still the W3 placeholder.
 */

import { generatorsAt } from "./edits.js";

const NS = "http://www.w3.org/2000/svg";

/* Okabe-Ito in config bus order, matching src/viz/network.py so a bus is the
   same hue in the PDF and on screen.

   This is a placeholder and it changes at W3, whose network map colours a bus
   by its LMP. Identity is the right encoding for a render that has no view to
   be part of yet; it is the wrong one for a finished map. What replaces it --
   which mark keeps identity, sequential level or diverging congestion, and
   what the domain is fixed to -- is settled at the top of W3. See CLAUDE.md,
   "Colour on the network map". Do not quietly turn this array into a ramp.

   Identity, not a ramp, and never cycled:
   the editor can add a seventh bus, and a palette that wrapped would give it
   bus A's colour and quietly assert they were the same thing. Past the end of
   the palette, identity has run out and the disc says so by going neutral. */
const BUS_HUE = ["#0072b2", "#e69f00", "#009e73", "#cc79a7", "#56b4e9", "#d55e00"];
const NO_HUE = "var(--ink-muted)";

export function hueFor(index) {
  return index < BUS_HUE.length ? BUS_HUE[index] : NO_HUE;
}

/* ------------------------------------------------------------- formatting */

/* A price. Two decimals, units on the column header once -- never repeated on
   every mark (CLAUDE.md, Register). */
export function usd(x) {
  return x.toFixed(2);
}

/* The settlement residual, the one number on this page whose interest is
   its smallness. Two decimals would print 0.00 for a genuine
   $0.004 break and for 3e-13 of float debris alike. So: exact zero prints
   bare, debris prints in exponent form and keeps its order of magnitude, and
   anything a person could notice prints in dollars. */
export function residual(x) {
  if (x === 0) return "0";
  return Math.abs(x) < 1e-6 ? x.toExponential(1) : x.toFixed(6);
}

/* ------------------------------------------------------------------- SVG */

function node(name, attrs = {}, text = null) {
  const e = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (text !== null) e.textContent = text;
  return e;
}

/* ------------------------------------------------------------ figure scale
 *
 * SVG text is in User Units, so it scales with the viewBox -- and the viewBox
 * has to fit whatever the editor builds, including a bus dragged far from the
 * rest. A font-size fixed in the stylesheet therefore renders at a size that
 * depends on the topology, which is how the first cut of this file put 20 px
 * labels on a page whose largest type is 10.5 (CLAUDE.md, "one typographic
 * hierarchy, strictly ordered").
 *
 * So every size below is a fraction of the viewBox span, chosen so that at
 * the figure's rendered width the result lands on the page's own hierarchy.
 * style.css carries the print figure's 10.5 / 9.5 / 8.5 pt as 1.05 / 0.95 /
 * 0.875 rem -- one pt to a tenth of a rem -- so a bus label is --type-title
 * and a branch label is --type-annot, in px at the browser's 16 px root:
 *
 *     bus label    16.8 px   = --type-title,  1.05rem
 *     wire label   14.0 px   = --type-annot,  0.875rem
 *
 * The fractions live here rather than in the stylesheet because only this
 * module knows the span. Colour stays in the stylesheet, which is the half
 * that does not depend on it.
 */
/* The rendered width, in CSS px, measured at draw time rather than asserted.
   It used to be a constant 496 matching #network's max-width, and W3.0's
   frame broke that: .frame .panel clears .figure's cap, so between 582 and
   959 px the SVG grew with the window and the bus labels went with it --
   29.6 px at a 959 px window, on a page whose largest type is 16.8. Measured
   instead, a label is --type-title at every width, which is what the
   hierarchy asks for. Falls back to 496 when the SVG is not laid out yet. */
const REM = 16;
let figurePx = 496;
const px = (n, span) => (n * span) / figurePx;
const rem = (n, span) => px(n * REM, span);

/* Branches between the same pair of buses, bowed apart so n parallel lines
   read as n lines. Parallel branches are physical and the engine solves them
   correctly (CLAUDE.md, "not a bug") -- drawing them on top of each other is
   how the editor would look like it had swallowed one. Offset 0 is a
   straight line, so the ordinary case is unbent. */
function bow(branches) {
  const seen = new Map();
  const order = new Map();
  for (const name of Object.keys(branches)) {
    const br = branches[name];
    const pair = [br.from, br.to].sort().join("\u0000");
    const n = seen.get(pair) ?? 0;
    seen.set(pair, n + 1);
    order.set(name, { pair, n });
  }
  const offsets = new Map();
  for (const [name, { pair, n }] of order) {
    const total = seen.get(pair);
    offsets.set(name, n - (total - 1) / 2);
  }
  return offsets;
}

/* Where a bus's name hangs: opposite the mean direction of its branches, so
 * the label sits on empty ground rather than across a line.
 *
 * CLAUDE.md resolves collisions by Moving Text, never by shrinking it, and
 * the print figures do this by hand -- src/viz/network.py carries a literal
 * per-bus table of anchors. A hand table cannot survive an editor that adds
 * buses, so the rule is computed instead. It reduces to "above" for a bus
 * with no branches at all, which is the one case with no direction to avoid.
 */
function labelDirection(bus, branches, at) {
  let ux = 0;
  let uy = 0;
  for (const br of Object.values(branches)) {
    const other = br.from === bus.name ? at.get(br.to) : br.to === bus.name ? at.get(br.from) : null;
    if (!other) continue;
    const dx = other.x - bus.x;
    const dy = other.y - bus.y;
    const len = Math.hypot(dx, dy) || 1;
    ux += dx / len;
    uy += dy / len;
  }
  const len = Math.hypot(ux, uy);
  if (len < 1e-9) return { x: 0, y: -1 };
  return { x: -ux / len, y: -uy / len };
}

/* The anchor that keeps the text clear of the disc it names, given that
   direction. A label placed to the right must start there; one placed
   above must sit on its baseline. */
function anchorFor(dir) {
  return {
    "text-anchor": dir.x > 0.3 ? "start" : dir.x < -0.3 ? "end" : "middle",
    "dominant-baseline": dir.y > 0.3 ? "hanging" : dir.y < -0.3 ? "auto" : "middle",
  };
}

/* The viewBox the drawing needs, padded. Fitted to the buses rather than
   fixed at the editor's 0-100 field, because a fixed box wastes half the
   panel on empty ground at case5's extent and would clip the moment a bus is
   dragged outside it. A floor on the span keeps a one-bus or two-bus network
   from being blown up to fill the panel. */
function viewBox(buses) {
  if (buses.length === 0) return { x: 0, y: 0, w: 100, h: 100, span: 100 };
  const xs = buses.map((b) => b.x);
  const ys = buses.map((b) => b.y);
  const lo = { x: Math.min(...xs), y: Math.min(...ys) };
  const hi = { x: Math.max(...xs), y: Math.max(...ys) };
  const span = Math.max(hi.x - lo.x, hi.y - lo.y, 40);
  const pad = span * 0.14;
  const w = Math.max(hi.x - lo.x, span * 0.5) + 2 * pad;
  const h = Math.max(hi.y - lo.y, span * 0.5) + 2 * pad;
  return {
    x: (lo.x + hi.x) / 2 - w / 2,
    y: (lo.y + hi.y) / 2 - h / 2,
    w,
    h,
    span: Math.max(w, h),
  };
}

/* The network as the editor declares it, not as a solve returned it. Two
   reasons, and the second is the load-bearing one:
     1. coordinates only exist here;
     2. a drag must redraw before the solve lands, or the map lags the hand
        by a round trip and the editor feels broken. Prices come from the
        response and go stale visibly (see markStale); topology does not.
*/
export function renderNetwork(svg, state) {
  svg.replaceChildren();
  figurePx = svg.clientWidth || 496;
  const at = new Map(state.buses.map((b) => [b.name, b]));
  const offsets = bow(state.branches);

  const box = viewBox(state.buses);
  svg.setAttribute("viewBox", `${box.x} ${box.y} ${box.w} ${box.h}`);
  const s = box.span;
  const size = {
    disc: px(14, s),
    ring: px(20, s),
    busText: rem(1.05, s), // --type-title
    wireText: rem(0.875, s), // --type-annot
    wire: px(1.6, s),
    halo: px(3.5, s),
    ringStroke: px(1, s),
    lift: px(27, s), // how far a bus label sits off its disc
    liftOverGens: px(60, s), // ... and how far when it must clear its units
    parallel: px(16, s), // how far apart n parallel branches bow
    /* W2.5. The transparent shapes that make a 14-unit disc and a 1.6-unit
       line comfortable to click. Pointer comfort only -- they carry no
       meaning, and nothing reads them but the hit test. */
    hitDisc: px(26, s),
    hitWire: px(12, s),
    /* W2.5. Generator marks, placed along the direction the label already
       computed as empty ground and spread across it. */
    genLift: px(35, s),
    genSide: px(13, s),
    genGap: px(19, s),
  };

  const wires = node("g", { class: "wires" });
  const labels = node("g", { class: "wire-labels" });
  for (const [name, br] of Object.entries(state.branches)) {
    const a = at.get(br.from);
    const b = at.get(br.to);
    // A branch naming a bus the editor has deleted. The engine refuses that
    // scenario with a sentence; the map simply does not draw a line to
    // nowhere, rather than throwing and blanking the whole picture.
    if (!a || !b) continue;

    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const len = Math.hypot(dx, dy) || 1;
    const off = offsets.get(name) * size.parallel;
    // Control point: the midpoint, pushed along the perpendicular. Both ends
    // stay on their buses, which a parallel straight line would not.
    const cx = (a.x + b.x) / 2 - (dy / len) * off * 2;
    const cy = (a.y + b.y) / 2 + (dx / len) * off * 2;
    const d = `M ${a.x} ${a.y} Q ${cx} ${cy} ${b.x} ${b.y}`;

    /* One group per branch, carrying the name and the focus. The hit path is
       first so the visible one paints over it; both are inside the group, so
       `closest("[data-branch]")` answers for either. */
    const g = node("g", {
      class: "branch",
      "data-branch": name,
      tabindex: "0",
      role: "button",
      "aria-label": `Line ${name}, ${br.from} to ${br.to}`,
    });
    g.append(
      node("path", { d, class: "wire-hit", "stroke-width": size.hitWire }),
      node("path", { d, class: "wire", "stroke-width": size.wire }),
    );
    wires.append(g);

    labels.append(
      node(
        "text",
        {
          // Quadratic midpoint, t = 1/2.
          x: (a.x + 2 * cx + b.x) / 4,
          y: (a.y + 2 * cy + b.y) / 4,
          class: "wire-label",
          "font-size": size.wireText,
          "stroke-width": size.halo,
        },
        name,
      ),
    );
  }

  const discs = node("g", { class: "buses" });
  const units = node("g", { class: "units" });
  state.buses.forEach((bus, i) => {
    const hue = hueFor(i);
    const gens = generatorsAt(state.fleet, bus.name);
    const dir = labelDirection(bus, state.branches, at);

    const g = node("g", {
      class: "bus",
      "data-bus": bus.name,
      tabindex: "0",
      role: "button",
      "aria-label":
        `Bus ${bus.name}` +
        (bus.name === state.slack ? ", the slack" : "") +
        (gens.length ? `, ${gens.length} generator(s)` : ", no generator"),
    });
    g.append(node("circle", { cx: bus.x, cy: bus.y, r: size.hitDisc, class: "hit" }));
    if (bus.name === state.slack) {
      // The slack is an accounting origin and no price depends on it
      // (trap 2), but it is a thing the page displays, so it is marked.
      g.append(
        node("circle", {
          cx: bus.x,
          cy: bus.y,
          r: size.ring,
          "stroke-width": size.ringStroke,
          class: "slack-ring",
        }),
      );
    }
    g.append(
      node("circle", {
        cx: bus.x,
        cy: bus.y,
        r: size.disc,
        fill: hue,
        "stroke-width": size.halo / 3,
        class: "disc",
      }),
    );
    const lift = gens.length ? size.liftOverGens : size.lift;
    g.append(
      node(
        "text",
        {
          x: bus.x + dir.x * lift,
          y: bus.y + dir.y * lift,
          class: "bus-label",
          "font-size": size.busText,
          "stroke-width": size.halo,
          ...anchorFor(dir),
        },
        bus.name,
      ),
    );
    discs.append(g);

    /* The units at this bus.
     *
     * W2.5 draws them because the editing grammar needs a target: Remove is
     * armed and then clicked, and a generator with no mark on the map could
     * only be removed by a second grammar somewhere else -- which is the one
     * thing CLAUDE.md's decision forbids.
     *
     * They are not labelled. Five more names at this scale collide with the
     * bus labels
     * and with each other, and CLAUDE.md resolves collisions by moving text
     * or cutting content, never by shrinking it. So identity is carried by
     * focus and hover -- the title element below is the native tooltip, the
     * aria-label is the same sentence for a screen reader, and the armed
     * readout names what is under the pointer. A generator gets a printed
     * name in W3's merit-order stack, which is a view with room for one.
     *
     * Placed along `dir`, which labelDirection already computed as the empty
     * ground around this bus, and spread across it so n units read as n.
     */
    const perp = { x: -dir.y, y: dir.x };
    gens.forEach(([name, spec], k) => {
      const slide = (k - (gens.length - 1) / 2) * size.genGap;
      const cx = bus.x + dir.x * size.genLift + perp.x * slide;
      const cy = bus.y + dir.y * size.genLift + perp.y * slide;
      const about =
        `Generator ${name} at ${bus.name}, ` +
        `${spec.pmax_mw} MW at $${spec.cost_usd_per_mwh.toFixed(2)}/MWh`;
      const u = node("g", {
        class: "unit",
        "data-gen": name,
        tabindex: "0",
        role: "button",
        "aria-label": about,
      });
      u.append(node("title", {}, about));
      u.append(
        node("rect", {
          x: cx - size.genSide,
          y: cy - size.genSide,
          width: size.genSide * 2,
          height: size.genSide * 2,
          class: "hit",
        }),
      );
      u.append(
        node("rect", {
          x: cx - size.genSide / 2,
          y: cy - size.genSide / 2,
          width: size.genSide,
          height: size.genSide,
          stroke: hue,
          "stroke-width": size.ringStroke * 1.4,
          class: "unit-mark",
        }),
      );
      units.append(u);
    });
  });

  svg.append(wires, labels, discs, units);
}

/* ---------------------------------------------------------------- tables */

function table(head, rows) {
  const t = document.createElement("table");
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  head.forEach((h, i) => {
    const th = document.createElement("th");
    th.textContent = h;
    if (i > 0) th.className = "num";
    hr.append(th);
  });
  thead.append(hr);
  const tbody = document.createElement("tbody");
  for (const row of rows) {
    const tr = document.createElement("tr");
    row.forEach((cell, i) => {
      const td = document.createElement("td");
      if (cell && typeof cell === "object") {
        td.textContent = cell.text;
        if (cell.swatch) {
          const dot = document.createElement("span");
          dot.className = "swatch";
          dot.style.background = cell.swatch;
          td.prepend(dot);
        }
      } else {
        td.textContent = cell;
      }
      if (i > 0) td.className = "num";
      tr.append(td);
    });
    tbody.append(tr);
  }
  t.append(thead, tbody);
  return t;
}

/* LMP per bus, for one hour. Read straight off cleared.lmp, which is one
   array per bus aligned to cleared.hours -- index, do not search. */
export function renderPrices(el, cleared, hour, order) {
  const rows = order.map((name, i) => [
    { text: name, swatch: hueFor(i) },
    cleared.lmp[name] ? usd(cleared.lmp[name][hour]) : "—",
  ]);
  el.replaceChildren(table(["Bus", "LMP ($/MWh)"], rows));
}

/* One row per island: its lambda, its buses, and its settlement residual --
 * all three for the same hour.
 *
 * Per island and per hour, never summed. Summing the islands would let a
 * positive residual in one cancel a negative one in the other, which is the
 * per-hour mistake one dimension over (CLAUDE.md, W1 islands).
 *
 * Islands are named by their slack because lambda is the LMP at the slack,
 * so the name is the honest one. The wire always carries lmbda keyed this
 * way -- one entry for a connected network, several for a cut one -- so
 * there is no shape here to branch on.
 */
export function renderIslands(el, cleared, hour) {
  const rows = Object.keys(cleared.lmbda).map((home) => [
    home,
    usd(cleared.lmbda[home][hour]),
    cleared.islands[home].length,
    residual(cleared.settlement[home].residual[hour]),
  ]);
  el.replaceChildren(
    table(["Island (named by its slack)", "λ ($/MWh)", "Buses", "Residual ($)"], rows),
  );
}

/* Prices on screen that no longer describe the network on screen. A solve was
   refused or superseded, so the map has moved and the numbers have not. Said,
   not hidden and not cleared: a blank table reads as "no prices exist", and a
   silent stale one is the same failure api.js's request coalescing removes,
   arriving by another door. */
export function markStale(on) {
  for (const panel of document.querySelectorAll("[data-results]")) {
    if (on) panel.dataset.stale = "true";
    else delete panel.dataset.stale;
  }
}
