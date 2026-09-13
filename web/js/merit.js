/* W3.4: the merit-order stack.
 *
 * Offers cheapest first, each a block as wide as its capacity and as tall as
 * its cost, with the part that actually ran filled in. The demand bids come
 * down from the other side, and lambda is a rule across the middle.
 *
 * Three things this view has to be honest about, and they are what most of
 * the code below is for.
 *
 * ONE STACK PER ISLAND. An island has its own energy balance and its own
 * lambda, so it has its own market and its own stack. Drawing the fleet as
 * one stack after a line is cut would put a generator in one island under
 * load in another, which is the single-balance-row bug of W1 redrawn as a
 * picture.
 *
 * THE STACK DOES NOT SET THE PRICE HERE. On a single bus the intersection is
 * lambda and the marginal unit's offer is the price. With a line binding,
 * neither is true: units run out of merit order, and three of case5's five
 * buses have an LMP equal to no offer at all. So the blocks are drawn in
 * merit order and filled by what the engine dispatched, and where those two
 * disagree the gap is visible -- a cheap block left empty with a dear one
 * filled beside it is congestion, and it is the most informative thing this
 * view can show. The prices themselves are the LMP panel's job.
 *
 * THE BIDS ARE OFF THE TOP OF THE SCALE. Firm load is valued at the offer
 * cap, $5000/MWh against offers of $10 to $40, so a y axis containing both
 * would draw the whole supply stack as a line one pixel thick. The axis is
 * therefore the offer range, and anything above it -- a bid at the cap, or
 * lambda in a scarcity hour -- is drawn at the ceiling, dashed, carrying its
 * own value as text. One rule, applied to both, so neither reads as a
 * magnitude the axis can be used to measure.
 *
 * Colour is identity, from the shared palette in fleet order, which is what
 * CLAUDE.md reserves for this view. It is fleet order and NOT merit position:
 * marginal cost is a lever, so the stack reorders under the reader's hand,
 * and a hue that belonged to the position rather than the unit would have
 * E1 change colour while the reader dragged its cost. src/viz/
 * merit_order.py does colour by position, and can: it is an M0 figure of
 * three units that nobody is dragging.
 *
 * The boundary rule holds. Every price and every MW here is a field of the
 * clear() return. What this file computes is where a block sits -- a
 * cumulative MW is an x coordinate, the same kind of arithmetic as the
 * percentages in splitRow -- and it never adds a price to a price.
 */

import { usd } from "./render.js";
import { genInk } from "./scales.js";

const NS = "http://www.w3.org/2000/svg";

/* The drawing is 480 units wide and renders into a panel about 500 px, so a
   unit is near enough a pixel and the type sizes below are the register's:
   --type-annot 14 px for a label, a little under it for a tick. */
const W = 480;
const H = 232;
const PAD = { l: 46, r: 14, t: 18, b: 38 };
const ANNOT = 13.5;
const TICK = 12;

/* Below this many units a block has no room for its name without overrunning
   the block beside it. Names are moved, never shrunk (CLAUDE.md, Register),
   so a block this narrow carries its name in the tooltip only. */
const NAME_ROOM = 30;

const px = (x) => Math.round(x * 100) / 100;

function node(name, attrs = {}, text = null) {
  const el = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  if (text !== null) el.textContent = text;
  return el;
}

function tip(el, text) {
  el.append(node("title", {}, text));
  return el;
}

/* An annotation with a bbox under it.
 *
 * A halo is enough for a block's name, which sits on empty ground or on a
 * pale fill. It is not enough for λ, which lands wherever the price lands --
 * on the first render "λ = $30.00" sat inside C1's solid fill, where
 * --ink-wire is unreadable and the halo only fringed it. CLAUDE.md's answer
 * is a bbox at 0.75 on the surface colour, and this is that.
 *
 * The width is estimated from the character count rather than measured: the
 * text is not in the document yet, and the only decision the number makes is
 * how wide a pale rectangle is.
 */
function annotation(text, x, y, anchor = "start") {
  /* 7.2 a character, measured against the rendered label rather than guessed:
     6.6 left the right-hand end of "λ = $30.00, one of several" hanging off
     its own box. */
  const w = text.length * 7.2 + 10;
  const g = node("g");
  g.append(
    node("rect", {
      x: px(anchor === "end" ? x - w + 5 : x - 5),
      y: px(y - ANNOT + 1),
      width: px(w),
      height: px(ANNOT + 4),
      class: "merit-bbox",
    }),
    node(
      "text",
      { x: px(x), y: px(y), class: "merit-annot", "font-size": ANNOT, "text-anchor": anchor },
      text,
    ),
  );
  return g;
}

/* The palette is scales.js's, because the map colours the same squares
   from the same function. The order is the solve's fleet order. */
function hue(cleared, name) {
  return genInk(cleared.generators, name);
}

/* Cheapest first. Ties break on fleet order so the stack is stable under a
   redraw: two units at the same offer must not swap places when the hour
   moves. */
function supplyBlocks(cleared, gens, hour) {
  const order = [...gens].sort((a, b) => {
    const d = cleared.gen_cost[a] - cleared.gen_cost[b];
    return d !== 0 ? d : cleared.generators.indexOf(a) - cleared.generators.indexOf(b);
  });
  let cum = 0;
  return order.map((g) => {
    const block = {
      name: g,
      cost: cleared.gen_cost[g],
      pmax: cleared.gen_pmax[g],
      run: cleared.dispatch[g][hour],
      status: cleared.gen_status[g][hour],
      headroom: cleared.headroom[g][hour],
      rc: cleared.reduced_cost[g][hour],
      lo: cum,
    };
    cum += block.pmax;
    block.hi = cum;
    return block;
  });
}

/* Dearest first, which is the order a demand curve is read in. An inelastic
   bid has no value at all -- null on the wire means it must be served and
   there is no price at which it walks -- so it sorts above every priced bid
   and is drawn at the ceiling with the word rather than a number. */
function demandBlocks(cleared, bids, hour) {
  const value = (b) =>
    cleared.bid_value[b] === null ? Infinity : cleared.bid_value[b];
  const order = [...bids].sort((a, b) => {
    const d = value(b) - value(a);
    return d !== 0 ? d : cleared.bids.indexOf(a) - cleared.bids.indexOf(b);
  });
  let cum = 0;
  return order.map((k) => {
    const block = {
      name: k,
      value: cleared.bid_value[k],
      mw: cleared.bid_mw[k][hour],
      served: cleared.served[k][hour],
      lo: cum,
    };
    cum += block.mw;
    block.hi = cum;
    return block;
  });
}

/* A round number at or above x: 1, 2 or 5 times a power of ten. The axis top
   is printed as a tick, and $52.00 is a tick nobody can read a value off --
   it is the dearest offer times a margin, which is an artifact of the margin
   and not a price. */
function nice(x) {
  const mag = 10 ** Math.floor(Math.log10(x));
  for (const step of [1, 2, 2.5, 5, 10]) {
    if (x <= step * mag + 1e-9) return step * mag;
  }
  return 10 * mag;
}

/* The y axis is the offer range and nothing else -- see the header. The
   margin gives the dearest block's name room above its own step, and the
   rounding is what makes the top tick readable. An island with no generator
   has no offer range, so it falls back to lambda and then to a nominal
   decade, which keeps the axis from collapsing to zero height. */
function ceiling(supply, lam) {
  const dearest = supply.length ? Math.max(...supply.map((b) => b.cost)) : 0;
  if (dearest > 0) return nice(dearest * 1.15);
  if (Number.isFinite(lam) && lam > 0) return nice(lam * 1.15);
  return 10;
}

function renderOne(cleared, hour, gens, bids, lam, verdict, label) {
  const wrap = document.createElement("div");
  wrap.className = "merit-plot";

  if (label) {
    const head = document.createElement("p");
    head.className = "merit-head";
    head.textContent = label;
    wrap.append(head);
  }

  const supply = supplyBlocks(cleared, gens, hour);
  const demand = demandBlocks(cleared, bids, hour);

  const ymax = ceiling(supply, lam);
  /* The x axis spans whichever side is longer, so a fleet that cannot cover
     its load shows as demand running off the end of the stack rather than as
     a demand curve quietly rescaled to fit it. */
  const xmax = Math.max(
    supply.length ? supply[supply.length - 1].hi : 0,
    demand.length ? demand[demand.length - 1].hi : 0,
    1,
  );

  const plotW = W - PAD.l - PAD.r;
  const plotH = H - PAD.t - PAD.b;
  const x = (mw) => px(PAD.l + (mw / xmax) * plotW);
  const y = (p) => px(PAD.t + (1 - Math.min(p, ymax) / ymax) * plotH);
  const base = y(0);

  const svg = node("svg", {
    class: "merit",
    viewBox: `0 0 ${W} ${H}`,
    role: "img",
    "aria-label":
      `Merit order: ${supply.length} generators offered, ` +
      `${demand.length} demand bids, λ ${usd(lam)} dollars per MWh`,
  });

  /* -------------------------------------------------------- supply blocks */

  const stack = node("g", { class: "merit-stack" });
  /* The names are painted after the demand curve and the λ rule, not with
     their own blocks. Their halo only wins against what is already on the
     canvas, and the demand curve's vertical drop went straight through
     A2 on the first render. */
  const names = node("g", { class: "merit-names" });
  for (const b of supply) {
    const ink = hue(cleared, b.name);
    const top = y(b.cost);
    const g = node("g", { class: "merit-block" });

    /* The whole capacity, pale: what the unit offered. */
    g.append(
      node("rect", {
        x: x(b.lo),
        y: top,
        width: px(x(b.hi) - x(b.lo)),
        height: px(base - top),
        fill: ink,
        "fill-opacity": 0.12,
        stroke: "var(--surface)",
        "stroke-width": 1,
      }),
    );

    /* The part that ran, solid, drawn from the block's own left edge. Where
       this stops short and a dearer block beside it is full, the dispatch is
       out of merit order and that is congestion. */
    if (b.run > 1e-9) {
      g.append(
        node("rect", {
          x: x(b.lo),
          y: top,
          width: px(x(b.lo + b.run) - x(b.lo)),
          height: px(base - top),
          fill: ink,
          "fill-opacity": 0.85,
          stroke: "var(--surface)",
          "stroke-width": 1,
        }),
      );
    }

    /* The offer itself: the step's tread. Drawn last so neither fill covers
       it, and it is the mark the reader reads the price off. */
    g.append(
      node("line", {
        x1: x(b.lo),
        y1: top,
        x2: x(b.hi),
        y2: top,
        stroke: ink,
        "stroke-width": 2,
      }),
    );

    if (x(b.hi) - x(b.lo) >= NAME_ROOM) {
      /* Left-aligned in its own block, except where that would run the name
         off the right edge of the drawing -- the dearest block is the last
         one and its name starts near the end of the axis. Roughly 6.5 units
         a character at 13.5; an estimate is enough, because the only
         decision it makes is which end to anchor. */
      const runsOff = x(b.lo) + 3 + b.name.length * 6.5 > W - PAD.r;
      names.append(
        node(
          "text",
          {
            x: runsOff ? px(x(b.hi) - 3) : px(x(b.lo) + 3),
            y: px(top - 4),
            class: "merit-name",
            "font-size": ANNOT,
            "text-anchor": runsOff ? "end" : "start",
          },
          b.name,
        ),
      );
    }

    /* Hover carries four decimals where the figure carries two, and the
       fields the block cannot draw: status, headroom, reduced cost. */
    tip(
      g,
      `${b.name}: offer $${b.cost.toFixed(2)}/MWh, capacity ` +
        `${b.pmax.toFixed(1)} MW\n` +
        `dispatch ${b.run.toFixed(4)} MW, ${b.status}, headroom ` +
        `${b.headroom.toFixed(4)} MW, reduced cost ${b.rc.toFixed(4)} $/MWh`,
    );
    stack.append(g);
  }
  svg.append(stack);

  /* --------------------------------------------------------- demand curve */

  /* A staircase from the dearest bid down, clamped at the ceiling. Clamped
     and not scaled: see the header. */
  const clipped = [];
  if (demand.length) {
    const pts = [];
    let prev = null;
    for (const b of demand) {
      const v = b.value === null ? Infinity : b.value;
      if (v > ymax) clipped.push(b);
      const at = y(v);
      if (prev !== null) pts.push(`L ${x(b.lo)} ${at}`);
      else pts.push(`M ${x(b.lo)} ${at}`);
      pts.push(`L ${x(b.hi)} ${at}`);
      prev = at;
    }
    pts.push(`L ${x(demand[demand.length - 1].hi)} ${base}`);
    svg.append(
      tip(
        node("path", { d: pts.join(" "), class: "merit-demand" }),
        demand
          .map(
            (b) =>
              `${b.name}: ${b.mw.toFixed(1)} MW at ` +
              (b.value === null ? "no price (inelastic)" : `$${b.value.toFixed(2)}/MWh`) +
              `, served ${b.served.toFixed(4)} MW`,
          )
          .join("\n"),
      ),
    );

    /* What the market declined to serve, marked on the axis under the bid it
       belongs to. Only reachable when a bid is outbid or an island cannot
       cover its load, and invisible on the default scenario, where every bid
       sits at the cap and is served in full. */
    let named = false;
    for (const b of demand) {
      if (b.served >= b.mw - 1e-6) continue;
      const from = x(b.lo + b.served);
      const to = x(b.hi);
      svg.append(
        tip(
          node("rect", {
            x: from,
            y: px(base - 3),
            width: px(to - from),
            height: 6,
            class: "merit-curtail",
          }),
          `${b.name}: ${(b.mw - b.served).toFixed(4)} MW not served`,
        ),
      );
      /* Once, on the first bar wide enough to hold the words. The bar is the
         only mark on this figure that is not about supply, and an unlabelled
         one is a red stripe on an axis. */
      if (!named && to - from >= NAME_ROOM * 2) {
        named = true;
        names.append(annotation("Not served", from + 3, base - 8));
      }
    }
  }

  /* ------------------------------------------------------------- lambda */

  const lamOver = lam > ymax;
  svg.append(
    node("line", {
      x1: PAD.l,
      y1: y(lam),
      x2: px(W - PAD.r),
      y2: y(lam),
      class: lamOver ? "merit-lambda-rule over" : "merit-lambda-rule",
    }),
  );
  /* Below the rule, except where below is off the bottom. Above puts the
     label in the same corner as the dearest block's name -- λ = $39.94 sat
     on top of `D1` on the first render -- and below it is the interior
     of that block, which is empty by construction: nothing is drawn above a
     block's own tread. A λ of zero is the exception, and it happens: an
     island with generation and no load prices at zero, and the label there
     landed on the x axis ticks. */
  const lamLow = base - y(lam) < ANNOT + 4;
  let lamText = lamOver ? `λ = $${usd(lam)}, above this scale` : `λ = $${usd(lam)}`;

  /* The flag W3.1 put on the wire, said where the number it qualifies is.
     An island with generation and no load prices anywhere between zero and
     the cheapest offer, and printing $0.00 bare would claim the market said
     something it did not (CLAUDE.md, W1 islands; trap 3). */
  if (verdict === "price_is_an_interval") lamText += ", one of several";
  else if (verdict === "dispatch_is_not_unique") lamText += ", on one of several dispatches";

  svg.append(
    annotation(lamText, W - PAD.r, y(lam) + (lamLow ? -6 : ANNOT + 2), "end"),
  );

  /* The bids that did not fit on the axis, said once rather than per step.
     Placed under the ceiling, left, where the dearest block's name is not. */
  if (clipped.length) {
    const v = clipped[0].value;
    svg.append(
      annotation(
        v === null
          ? "Demand bids are inelastic — no price, drawn at the ceiling"
          : `Demand bids at $${usd(v)}/MWh, above this scale`,
        PAD.l + 4,
        /* A line lower when λ is clamped to the ceiling as well, because both
           are then annotations of the same rule and the long one runs under
           the short one. */
        PAD.t + ANNOT + 5 + (lamOver ? ANNOT + 3 : 0),
      ),
    );
  }

  svg.append(names);

  /* --------------------------------------------------------------- axes */

  const axes = node("g", { class: "merit-axes" });
  axes.append(
    node("line", { x1: PAD.l, y1: base, x2: px(W - PAD.r), y2: base }),
    node("line", { x1: PAD.l, y1: PAD.t, x2: PAD.l, y2: base }),
  );
  svg.append(axes);

  const tickText = (tx, ty, text, anchor) =>
    node(
      "text",
      { x: tx, y: ty, class: "merit-tick", "font-size": TICK, "text-anchor": anchor },
      text,
    );
  svg.append(
    tickText(px(PAD.l - 6), px(base + 4), "0", "end"),
    tickText(px(PAD.l - 6), px(PAD.t + 4), String(+ymax.toFixed(2)), "end"),
    tickText(PAD.l, px(base + TICK + 4), "0", "middle"),
    tickText(px(W - PAD.r), px(base + TICK + 4), xmax.toFixed(0), "end"),
  );

  svg.append(
    node(
      "text",
      {
        x: px(PAD.l + plotW / 2),
        y: px(H - 4),
        class: "merit-axis-name",
        "font-size": ANNOT,
        "text-anchor": "middle",
      },
      "Cumulative capacity (MW)",
    ),
  );
  svg.append(
    node(
      "text",
      {
        x: 13,
        y: px(PAD.t + plotH / 2),
        class: "merit-axis-name",
        "font-size": ANNOT,
        "text-anchor": "middle",
        transform: `rotate(-90 13 ${px(PAD.t + plotH / 2)})`,
      },
      "Offer price ($/MWh)",
    ),
  );

  wrap.append(svg);
  return wrap;
}

export function renderMerit(el, cleared, hour) {
  el.replaceChildren();

  const homes = Object.keys(cleared.lmbda);
  const many = homes.length > 1;

  for (const home of homes) {
    const here = new Set(cleared.islands[home]);
    const gens = cleared.generators.filter((g) => here.has(cleared.gen_bus[g]));
    const bids = cleared.bids.filter((b) => here.has(cleared.bid_bus[b]));
    const lam = cleared.lmbda[home][hour];

    /* An island with neither an offer nor a bid has no market to draw. Named
       rather than dropped, so a cut that stranded a bus is visible here as
       well as on the map. */
    if (!gens.length && !bids.length) {
      const p = document.createElement("p");
      p.className = "note";
      p.textContent = `Island ${home}: no generator and no bid.`;
      el.append(p);
      continue;
    }

    el.append(
      renderOne(
        cleared,
        hour,
        gens,
        bids,
        lam,
        cleared.uniqueness[home].verdict[hour],
        many ? `Island ${home}` : null,
      ),
    );
  }
}
