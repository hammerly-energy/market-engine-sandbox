/* W3.11: the Timeline.
 *
 *     Timeline
 *     [Play]  ─────────────○──────────────      the hour, over the day
 *        A    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 *        B    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 *        C    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 *        D ○  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 *        E    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
 *     Hour 19 of 24            LMP ($/MWh) ▬ $10.00 $39.94
 *
 * One row per bus, one column per hour, and the cell is that bus's LMP. It
 * began at W3.10 as a seventh view sitting with the other six, and it is a
 * control now: the hour slider's track runs the width of the band, over the
 * same 24 hours, so the thumb sits on the column it names.
 *
 * THE FIELD IS THE TRACK'S SCALE, which is the whole reason the two are one
 * panel. Every other lever on this page moves a number against a rail with
 * nothing on it; this one moves a number against a picture of what the
 * number selects. A visitor dragging toward the dark middle of the day can
 * see the evening before they arrive at it.
 *
 * THE SLIDER IS ALSO THE TIME AXIS, so there is no row of hour labels under
 * the field. The track carries ticks every six hours -- the interval the
 * print figures rule a 24-hour series at -- and the band breaks at the same
 * three places, so the rhythm is stated twice and read once. The current
 * hour is a number in the footer rather than twenty-four numbers under the
 * field, which is what a control's readout is for.
 *
 * THE ROWS ARE SEPARATED, unlike W3.10's contiguous block. A gap and a
 * hairline make each bus its own series rather than one surface with five
 * bands in it, which is the right reading: these are five prices, not a
 * two-dimensional quantity. It also gives the thumb somewhere to be. The
 * cost is that the fan between B, C and D is a shade harder to see as one
 * shape, and that is the trade the sketch makes deliberately.
 *
 * THE SCALE IS THE MAP'S, not a second one. priceInk on priceDomain is what
 * inks the bus rings and the LMP panel's bars, so a dark cell here and a
 * dark ring there are the same price. A field that re-derived its own domain
 * would be a third scale on a page that has settled on one.
 *
 * It costs the second channel. The map carries price twice -- in lightness
 * and in ring width -- and redundancy is what survives a grayscale print and
 * a cheap monitor. A cell is a filled rectangle and has only lightness. That
 * is the honest trade for a field of 120 numbers: there is no width to
 * spend, and the exact price is on hover, which the interactive register
 * allows to carry precision the figure does not.
 *
 * The interval dot is W3.9's rule in a fourth place. An hour the engine
 * flags `price_is_an_interval` keeps its ink, because the engine returned
 * that number and suppressing it would be the page deciding an answer was
 * too ambiguous to show. It takes a hollow dot on top, which says: do not
 * read this cell off the ramp. Measured, --surface against the ramp's ends:
 *
 *     #fcfcfb on #919191   3.07:1     the cheap end, the worst case
 *     #fcfcfb on #242424  15.12:1
 *
 * Both clear the 3:1 a non-text mark is held to, and 3.07 is the figure the
 * ramp's own lightest stop was accepted at. The hour cursor takes the same
 * ink for the same reason: at --ink it was 1.31:1 on the dear end and
 * vanished, which W3.10 found by rendering the picture and looking at it.
 *
 * The flag is per island and per hour, so a cell is dotted in the hours it
 * is an interval in and plain in the rest. That is a different test from the
 * one priceDomain runs, which asks whether a bus is an interval in EVERY
 * hour -- a bus with no market at all, which has no price to put on the
 * domain. An ordinary breakpoint is a few hours of the twenty-four and
 * belongs on the scale.
 *
 * CLICKING A COLUMN PICKS THAT HOUR, and the pick is the slider's: onPick
 * hands it to main.js, which writes state.hour, syncs the thumb and
 * repaints. There is no second piece of hour state and the two halves of
 * this panel cannot disagree.
 *
 * No keyboard path on the cells, and that is not the W2.5 gap. W2.5's rule
 * exists because a structural edit had NO keyboard route at all; the hour
 * has one, it is the slider directly above, and it is fully operable. The
 * cells are a redundant pointer affordance on a control already reachable,
 * so making 120 of them focusable would add 120 tab stops in front of the
 * rail below and reach nothing new.
 *
 * The boundary rule holds. Every number is cleared.lmp or
 * cleared.uniqueness. What this file computes is which grey a number takes,
 * which is the browser picking a colour.
 */

import { priceDomain, priceInk, rampCss } from "./scales.js";
import { usd, verdictFor, verdictLabel } from "./render.js";

/* The band breaks here -- before hour 7, 13 and 19, one-based. The same
   six-hour rhythm the slider's ticks carry, in the other channel. */
const BREAK_BEFORE = new Set([7, 13, 19]);

function cell(text, cls) {
  const el = document.createElement("span");
  el.className = cls;
  el.textContent = text;
  return el;
}

/* ONE listener on the panel, mounted once, not one per cell and not one per
 * paint.
 *
 * Both halves of that matter. A listener per cell would be 120 additions and
 * 120 removals a frame through a drag. And a listener added inside
 * renderTimeline would stack: replaceChildren drops the children and leaves
 * every listener on the container itself, so after a hundred paints a click
 * would fire a hundred picks. Mounted once, from main.js, beside the other
 * things that are wired once.
 */
export function mountTimelinePicker(el, onPick) {
  el.dataset.pick = "true";
  el.addEventListener("click", (ev) => {
    const mark = ev.target.closest("[data-hour]");
    if (!mark || !el.contains(mark)) return;
    onPick(Number(mark.dataset.hour));
  });
}

/* The name column. The slack carries a ring, the same mark the map puts
   around it, because lambda is the LMP at the slack and this row is
   therefore the row an island's lambda is read off. */
function name(bus, isSlack) {
  const el = document.createElement("span");
  el.className = "tl-name";
  el.append(cell(bus, "tl-bus"));
  if (isSlack) {
    const mark = cell("", "tl-slack");
    mark.title = `${bus} is the slack. λ is the LMP here, so this row is λ.`;
    el.append(mark);
  }
  return el;
}

function row(bus, cleared, hour, domain) {
  const el = document.createElement("div");
  el.className = "tl-row";
  el.append(name(bus, bus === cleared.slack));

  const band = document.createElement("div");
  band.className = "tl-band";

  const series = cleared.lmp[bus];

  /* A bus the last answer does not carry: added since the solve and priced a
     round trip later. Named, with an empty band, so the row count matches
     the bus list rather than the bus quietly vanishing from the day. */
  if (!series) {
    band.classList.add("tl-band-empty");
    band.title = `${bus} is not in the last answer.`;
    el.append(band);
    return el;
  }

  for (let t = 0; t < series.length; t += 1) {
    const v = series[t];
    const box = document.createElement("div");
    box.className = "tl-cell";
    box.dataset.hour = String(t);
    box.style.background = priceInk(v, domain);
    if (BREAK_BEFORE.has(t + 1)) box.classList.add("tl-sixth");
    if (t === hour) box.classList.add("tl-now");

    const verdict = verdictFor(cleared, bus, t);
    if (verdict === "price_is_an_interval") box.classList.add("tl-interval");

    /* Four decimals where the cell is a grey. The interactive register lets
       a tooltip carry precision the figure does not; it may not carry an
       argument the figure needed to make itself. */
    box.title =
      `${bus}, hour ${t + 1}: $${v.toFixed(4)}/MWh\n` +
      (verdict ? verdictLabel(verdict) : "unique") +
      "\nClick to move every view to this hour.";

    band.append(box);
  }

  el.append(band);
  return el;
}

/* The footer: the control's readout on the left, the panel's key on the
 * right, on one line.
 *
 * The readout is here rather than at the end of the track because the track
 * has to be exactly as wide as the band under it, and a number at its end
 * would shorten it.
 *
 * The key is the panel's, not the band's: the map above it inks its rings
 * from this same domain through this same function, and it carried a second
 * copy of this key until the two views were merged. One key, at the foot of
 * the panel both figures sit in.
 *
 * It is therefore drawn as a wedge, which the map's copy was and this was
 * not. A heatmap cell carries the price in lightness alone, but a bus ring
 * carries it in lightness and in width, and a flat bar keys only half of
 * that. Thin and pale at the cheap end, thick and dark at the dear one.
 */
function footer(cleared, hour, domain) {
  const el = document.createElement("div");
  el.className = "tl-footer";

  const now = document.createElement("p");
  now.className = "tl-readout";
  now.textContent = `Hour ${hour + 1} of ${cleared.hours.length}`;

  const key = document.createElement("div");
  key.className = "tl-key";

  const label = cell("LMP ($/MWh)", "tl-key-name");

  const ramp = document.createElement("div");
  ramp.className = "tl-ramp";
  ramp.style.background = rampCss();

  const ends = document.createElement("p");
  ends.className = "tl-ends";
  ends.append(cell(`$${usd(domain.lo)}`, ""), cell(`$${usd(domain.hi)}`, ""));

  const scale = document.createElement("div");
  scale.className = "tl-scale";
  scale.append(ramp, ends);

  key.append(label, scale);
  el.append(now, key);
  return el;
}

export function renderTimeline(el, cleared, hour, order) {
  el.replaceChildren();

  const domain = priceDomain(cleared);
  if (!domain) {
    el.append(cell("No priced bus in the last answer.", "note"));
    return;
  }

  /* One group per island, for the reason the flows and units panels group:
     each island answers its own energy balance, and a single block of rows
     would put two markets under one heading. The scale is shared across them
     so two islands' days are read against one ramp. */
  const homes = Object.keys(cleared.islands);
  const many = homes.length > 1;
  const placed = new Set();

  for (const home of homes) {
    const here = new Set(cleared.islands[home]);
    const mine = order.filter((b) => here.has(b));
    if (!mine.length) continue;

    const group = document.createElement("div");
    group.className = "tl-group";

    if (many) {
      const head = document.createElement("p");
      head.className = "tl-island";
      head.textContent = `Island ${home}`;
      group.append(head);
    }

    for (const bus of mine) {
      group.append(row(bus, cleared, hour, domain));
      placed.add(bus);
    }
    el.append(group);
  }

  /* Buses the engine priced in no island. None today; there would be if a
     solve and the editor ever disagreed about the bus list, and a row that
     silently vanished would be the harder failure to see. */
  const orphans = order.filter((b) => !placed.has(b));
  if (orphans.length) {
    const group = document.createElement("div");
    group.className = "tl-group";
    const head = document.createElement("p");
    head.className = "tl-island";
    head.textContent = "Not in the last answer";
    group.append(head);
    for (const bus of orphans) group.append(row(bus, cleared, hour, domain));
    el.append(group);
  }

  el.append(footer(cleared, hour, domain));
}
