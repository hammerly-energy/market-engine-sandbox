/* W3.7: generation by unit.
 *
 * One row per generator, all of them on ONE shared MW axis:
 *
 *            Dispatch against capacity      Status    Offer  Disp.  Head.    rc
 *   A1  A    ┃━━━┤                         at_max    14.00   40.0    0.0  -4.00
 *   A2  A    ┃━━━━━━━━━━━┤                 at_max    15.00  170.0    0.0  -5.00
 *   C1  C    ┃━━━━━━━━━━━━━━━━┼──────┤     interior  30.00  323.5  196.5   0.00
 *   D1  D    ┃┼───────────┤                off       40.00    0.0  200.0  -0.06
 *   E1  E    ┃━━━━━━━━━━━━━━━━━━━━━━━━━┤   at_max    10.00  600.0    0.0  29.94
 *            0                            600 MW
 *
 * The BAR is dispatch, from zero. The TICK is that unit's capacity. The gap
 * between them is headroom, which is why headroom is a column and a length
 * at once -- the number and the picture are the same fact, and the panel
 * prints the engine's field rather than measuring its own bar.
 *
 * The axis is shared rather than each track running 0 to that unit's own
 * capacity. A per-unit track draws A1 at 40 / 40 and E1 at 600 / 600 as the
 * same full bar, which is a false equality of MW: the two units are fifteen
 * times apart and the picture said they were the same. Shared, the
 * ticks land in different places and the fleet's shape is visible before any
 * number is read.
 *
 * WHAT THE PANEL DOES NOT CLAIM. A unit sitting interior is not "the
 * marginal unit" -- under congestion there is no single one, and case5's
 * peak hour has two units interior at once. The three words are a statement
 * about dispatch; rc is what that position is worth; the LMP panel is where
 * the prices are. gen_status and reduced_cost are separate fields of the
 * clear() return for exactly this reason, and they are separate columns
 * here.
 *
 * One case reads like a contradiction and is not: at_max with rc = 0. The
 * unit is full and indifferent at once, so load has landed exactly on a
 * capacity breakpoint and the price there is an interval. Trap 3, and the
 * uniqueness flag in the LMP panel is where it is named.
 *
 * Colour is identity, from the shared palette in fleet order -- the same
 * function that inks the merit stack's blocks and the map's generator
 * squares, so a reader can carry E1 from one to the other. Rows are in
 * fleet order for the same reason: the hue belongs to the position, and a
 * panel whose colours come from fleet order and whose rows come from cost
 * order would make the reader hold two orderings at once. Cost order is the
 * merit stack's, and that view exists.
 *
 * The boundary rule holds. Dispatch, capacity, headroom, status, offer and
 * reduced cost are all fields of the clear() return. What this file computes
 * is how long a bar is, which is geometry.
 */

import { usd } from "./render.js";
import { capacityDomain, genInk } from "./scales.js";

function cell(text, cls) {
  const el = document.createElement("span");
  el.className = cls;
  el.textContent = text;
  return el;
}

function header() {
  const row = document.createElement("div");
  row.className = "unit-row unit-head";
  row.append(
    cell("Unit", "unit-name"),
    cell("Bus", "unit-bus"),
    /* The bar is dispatch and the tick is capacity, so the column is named
       for both. Units are on the axis below it, once. */
    cell("Dispatch against capacity", "unit-track-head"),
    cell("Status", "unit-status"),
    cell("Offer ($/MWh)", "unit-num"),
    cell("Dispatch (MW)", "unit-num"),
    cell("Headroom (MW)", "unit-num"),
    cell("rc ($/MWh)", "unit-num"),
  );
  return row;
}

/* How the sign of rc reads, in the words pricing.reduced_costs uses. Printed
   in the tooltip rather than as a column: it is a reading of a number the row
   already carries, and a column of sentences would be the panel arguing. */
function sense(rc) {
  if (rc > 1e-9) return "the price at its bus beats its offer, so it wants to sell more";
  if (rc < -1e-9) return "the price does not cover its offer, so it is off";
  return "indifferent: its offer is the price at its bus";
}

function row(name, cleared, hour, domain) {
  const el = document.createElement("div");
  el.className = "unit-row";

  const label = cell(name, "unit-name");
  const bus = cleared.gen_bus[name];
  const track = document.createElement("div");
  track.className = "unit-track";

  const series = cleared.dispatch[name];

  /* A unit the last answer does not carry: added since the solve, or gone
     from it. Named with no bar, so the row count matches the fleet. */
  if (!series) {
    el.append(label, cell(bus ?? "—", "unit-bus"), track,
              cell("—", "unit-status"), cell("—", "unit-num"),
              cell("—", "unit-num"), cell("—", "unit-num"),
              cell("—", "unit-num"));
    return el;
  }

  const mw = series[hour];
  const pmax = cleared.gen_pmax[name];
  const head = cleared.headroom[name][hour];
  const status = cleared.gen_status[name][hour];
  const offer = cleared.gen_cost[name];
  const rc = cleared.reduced_cost[name][hour];

  /* The capacity, as a tick, drawn before the bar so a full bar ends on its
     tick rather than under it. Darker when the unit is actually at it --
     taken from status, which is the engine's own test against its own
     tolerance and not this file comparing two floats. */
  const tick = document.createElement("div");
  tick.className = status === "at_max" ? "unit-tick full" : "unit-tick";
  tick.style.left = `${(pmax / domain) * 100}%`;

  /* The origin. An off unit draws a bar of zero width, and without this the
     row would be an empty strip -- indistinguishable from a unit the answer
     does not carry, which is the row above. */
  const zero = document.createElement("div");
  zero.className = "unit-zero";

  const bar = document.createElement("div");
  bar.className = "unit-bar";
  bar.style.width = `${(mw / domain) * 100}%`;
  bar.style.background = genInk(cleared.generators, name);

  track.append(tick, bar, zero);

  el.append(
    label,
    cell(bus, "unit-bus"),
    track,
    /* The engine's own three words, verbatim. They are identifiers from the
       data and keep their literal form; the caption defines them. */
    cell(status, "unit-status"),
    cell(usd(offer), "unit-num"),
    cell(mw.toFixed(1), "unit-num"),
    cell(head.toFixed(1), "unit-num"),
    /* Signed, and printed even at zero. Zero rc is a measurement here -- it
       is what "interior" means in money -- unlike an unbinding mu, which is
       a price that does not exist. */
    cell(usd(rc), "unit-num"),
  );

  el.title =
    `${name} at bus ${bus}: ${mw.toFixed(4)} of ${pmax.toFixed(1)} MW, ` +
    `${head.toFixed(4)} MW of headroom\n` +
    `Offer $${offer.toFixed(2)}/MWh, ${status}\n` +
    `rc $${rc.toFixed(4)}/MWh — ${sense(rc)}`;

  return el;
}

/* The axis, under the tracks and in their column, so its ends land on the
   ends of every track. One-sided: dispatch runs from zero up, and the right
   end is the largest capacity in the fleet, which is a tick that exists
   rather than a rounded number nobody offered. */
function axis(domain) {
  const wrap = document.createElement("div");
  wrap.className = "unit-row unit-axis-row";

  const ax = document.createElement("div");
  ax.className = "unit-axis";
  ax.append(cell("0", "unit-axis-lo"), cell(`${domain} MW`, "unit-axis-hi"));

  wrap.append(
    cell("", "unit-name"), cell("", "unit-bus"), ax,
    cell("", ""), cell("", ""), cell("", ""), cell("", ""), cell("", ""),
  );
  return wrap;
}

export function renderUnits(el, cleared, hour) {
  el.replaceChildren();

  if (!cleared.generators.length) {
    el.append(cell("No generator in the last answer.", "note"));
    return;
  }

  const domain = capacityDomain(cleared);

  /* One group per island when a cut has made more than one. A unit answers
     its own island's energy balance and no other, so a single list would put
     a generator under load it cannot reach -- the single-balance-row bug of
     W1, redrawn as a table. */
  const homes = Object.keys(cleared.islands);
  const mine = {};
  for (const home of homes) mine[home] = [];
  for (const g of cleared.generators) {
    const home = cleared.island_of[cleared.gen_bus[g]];
    if (home in mine) mine[home].push(g);
  }
  const many = homes.filter((h) => mine[h].length).length > 1;

  for (const home of homes) {
    if (!mine[home].length) continue;

    const group = document.createElement("div");
    group.className = "unit-group";

    if (many) {
      const head = document.createElement("p");
      head.className = "unit-island";
      head.textContent = `Island ${home}`;
      group.append(head);
    }

    group.append(header());
    for (const name of mine[home]) group.append(row(name, cleared, hour, domain));
    group.append(axis(domain));
    el.append(group);
  }
}
