/* W3.2: the map's price scale. Colour only -- this module maps a number the
 * engine returned onto a hex string, which is the browser picking a colour
 * and not the browser doing market arithmetic. No number here reaches the
 * wire, and no number on screen is computed here.
 *
 * Two decisions are baked in, and both were measured rather than argued.
 *
 * Identity is gone from the bus. A bus used to be an Okabe-Ito hue matching
 * src/viz. It is now a neutral disc with its name inside it and a ring that
 * carries the price. So the map has two coloured marks -- rings and lines --
 * and they must not be confused for one another at any point on either
 * scale.
 *
 * The ring therefore takes no hue at all. The line ramp runs blue to
 * vermillion, and under deuteranopia every warm hue collapses toward that
 * vermillion and every cool hue toward that blue. There is no third hue
 * free on this map. So the channels split: lines carry hue, and carry
 * direction with it; buses carry lightness, and carry level with it. Nothing
 * collides under any colour vision, and the map is literally rather than
 * approximately grayscale-safe, which is what the print register asks for.
 *
 *     bus ring, neutral, L* 60 -> 14, against --surface #fcfcfb
 *
 *       cheap   #919191   3.07:1      every stop clears the 3:1 a
 *               #7d7d7d   4.01:1      non-text mark is held to, so
 *               #6a6a6a   5.27:1      "every state is visible" is a
 *               #575757   7.04:1      measurement here and not a hope
 *               #454545   9.34:1
 *       dear    #242424  15.12:1
 *
 * The lightest stop is close to the wire grey #8a8880 that paints an idle
 * line, 3.46:1. They are a thick ring and a thin line and never touch, but
 * it is the one place on the map where two scales come near each other.
 */

/* The ramp's ends, in CIE L*. Interpolating in L* rather than in sRGB is
   what makes the steps evenly spaced to the eye; the sRGB midpoint of the
   same two greys sits four L* units light of centre. */
const L_CHEAP = 60;
const L_DEAR = 14;

/* No price to show: before the first solve lands, or a bus the response does
   not carry. Dashed rather than pale -- a pale ring is the cheap end of the
   ramp and would read as a price of zero. */
export const NO_PRICE = "var(--ink-muted)";

/* L* to an sRGB grey. a* = b* = 0, so the three channels are equal and the
   conversion is one dimension of the full Lab transform. */
function greyFromL(L) {
  const fy = (L + 16) / 116;
  const y = fy ** 3 > 0.008856 ? fy ** 3 : (fy - 16 / 116) / 7.787;
  const c = y <= 0.0031308 ? y * 12.92 : 1.055 * y ** (1 / 2.4) - 0.055;
  const v = Math.round(Math.min(Math.max(c, 0), 1) * 255);
  return `#${v.toString(16).padStart(2, "0").repeat(3)}`;
}

/* The domain, fixed across the day and reported so it can be printed.
 *
 * Across the day, not per hour: a scale that rescaled when the hour moved
 * would make the colour change when only the scale changed, and a visitor
 * scrubbing the day would read that as a price change. It is the same
 * failure as a UI that animates prices sliding when the slack moves.
 *
 * It is not fixed across the session. A new solve is a different market and
 * its prices can leave the old domain entirely -- clamping them would hide
 * the most interesting thing a lever can do. The bounds are printed instead,
 * so a domain that moved is visible as a domain that moved.
 */
export function priceDomain(cleared) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const bus of cleared.buses) {
    for (const v of cleared.lmp[bus]) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  return Number.isFinite(lo) ? { lo, hi } : null;
}

/* Where a price sits on its domain, 0 at the cheap end and 1 at the dear.
   A flat day has no domain to sit on and everything takes the midpoint,
   which says "these are all the same price" rather than picking an end. */
export function priceAt(v, domain) {
  if (!domain) return 0.5;
  const span = domain.hi - domain.lo;
  if (span < 1e-9) return 0.5;
  return Math.min(Math.max((v - domain.lo) / span, 0), 1);
}

export function priceInk(v, domain) {
  return greyFromL(L_CHEAP + (L_DEAR - L_CHEAP) * priceAt(v, domain));
}

/* The ramp as CSS, for the legend. Built from priceInk so the legend cannot
   drift from the marks it explains. */
export function rampCss(steps = 9) {
  const stops = [];
  for (let i = 0; i < steps; i += 1) {
    const t = i / (steps - 1);
    stops.push(greyFromL(L_CHEAP + (L_DEAR - L_CHEAP) * t));
  }
  return `linear-gradient(to right, ${stops.join(", ")})`;
}

/* ------------------------------------------------ the generator palette
 *
 * Identity, in fleet order, never cycled. Okabe-Ito, the same five hues and
 * the same order src/viz/ assigns, so a unit in a print figure and a unit on
 * screen are the same colour.
 *
 * It lives here rather than in either view because two views read it: the
 * merit-order stack colours its blocks, and the map colours the square. A
 * second copy would be a second palette, and it would drift.
 *
 * Fleet order is a position, so removing a unit recolours the units after
 * it. Measured: delete park_city, solitude and sundance and brighton goes
 * from --hue-4 to --hue-1. The alternatives are worse. Merit position moves
 * under the cost slider, which is a far more frequent act than deleting a
 * unit, and a hash of the name onto five hues collides -- two units the same
 * colour is a stronger false claim than one unit changing colour in the same
 * edit that removed its neighbour.
 *
 * The palette holds five. A sixth generator takes the neutral ink rather
 * than reusing a hue, because a repeated hue would assert two units are the
 * same unit.
 */
export function genInk(order, name) {
  const i = order.indexOf(name);
  return i >= 0 && i < 5 ? `var(--hue-${i})` : "var(--ink-2)";
}

/* ------------------------------------------------- the flow scale, W3.6
 *
 * Three colours and no ramp between them. A line's HUE is the SIGN of its
 * flow and nothing else:
 *
 *     f < 0   teal    power runs to -> from
 *     f = 0   grey    idle
 *     f > 0   blue    power runs from -> to
 *
 * Magnitude is carried by WIDTH, on a shared MW domain, so hue is left to do
 * one job. The continuous ramp this replaced tried to carry direction and
 * loading at once, and the loading half was crushed the moment a binding line
 * got a dark casing behind it -- the core became a stripe and the hue with it.
 *
 * It also removes an encoding that could not be honest about an unrated line.
 * The old ramp was keyed to f / limit, so a line with no rating sat at the
 * neutral forever however much power it carried. A sign has an answer for
 * every line.
 *
 * Measured on --surface #fcfcfb:
 *
 *     blue   #0072b2   5.05:1
 *     teal   #007c54   5.10:1
 *     grey   #8a8880   3.46:1
 *
 * Both hues clear the 3:1 a non-text mark is held to, and they are within
 * 0.05 of each other, so neither direction reads as the heavier one. That
 * matters now that lightness carries nothing for a line: two marks at the
 * same lightness cannot be mistaken for a magnitude.
 *
 * The teal is the Okabe-Ito bluish green #009e73 taken from L* 57.7 to 45 so
 * it balances the blue; at its own lightness it is 3.33:1, which clears the
 * floor but sits paler than the blue and would have read as the weaker
 * direction.
 *
 * DIRECTION DOES NOT SURVIVE colour blindness, and this was asserted here for
 * a phase before anyone measured it. Telling the two hues apart, simulated
 * with Vienot 1999: protan 1.56:1, deutan 1.49:1, tritan 1.44:1. The
 * blue/vermillion pair this replaced was no better -- 1.10, 1.77, 2.35 -- so
 * neither scheme ever carried direction to a colour-blind reader. It is
 * carried by position in the flows panel, where the bar sits on the side of
 * zero its flow is on, and that is the channel that actually works.
 */

export const FLOW_POS = "#0072b2";
export const FLOW_NEG = "#007c54";
export const FLOW_ZERO = "#8a8880";

/* A solver returns 1e-14 for a line carrying nothing. Below this a flow is
   idle and takes the neutral rather than a direction it does not have. */
const IDLE_MW = 1e-9;

export function flowInk(mw) {
  if (mw > IDLE_MW) return FLOW_POS;
  if (mw < -IDLE_MW) return FLOW_NEG;
  return FLOW_ZERO;
}

/* The MW domain every flow mark is drawn on -- the panel's axis and the map's
 * wire widths alike, so a wire that is thick there is a long bar here.
 *
 * It spans the flows AND the finite ratings, because the panel draws a tick
 * at each rating and a tick outside its own axis is a mark with nowhere to
 * go. An unrated line contributes nothing, which is why an infinite rating
 * does not blow the scale up.
 *
 * Fixed across the day for the reason priceDomain gives: a scale that
 * rescaled when the hour moved would make a mark change when only the scale
 * changed. Re-derived per solve, and printed, so a domain that moved is
 * visible as a domain that moved.
 */
export function flowDomain(cleared) {
  let hi = 0;
  for (const l of cleared.lines) {
    /* Every hour, not this one. The scale is fixed across the day so that
       scrubbing the hour never rescales a mark. */
    for (const v of cleared.flows[l]) hi = Math.max(hi, Math.abs(v));
    /* Finite ratings count too, because the panel draws a tick at each one
       and a tick outside its own axis is a mark with nowhere to go. An
       unrated line contributes nothing, which is why an infinite rating does
       not blow the scale up. */
    const limit = cleared.limits[l];
    if (limit !== null) hi = Math.max(hi, Math.abs(limit));
  }
  return hi > 0 ? Math.ceil(hi / STEP) * STEP : STEP;
}

/* The axis ends on a multiple of this. 355.4 is an end nobody can read a
   value off -- it is one hour's largest flow, which is an accident of the
   data -- and 50 MW is fine enough that rounding up never leaves the longest
   bar stranded in the middle of the track. */
const STEP = 50;
