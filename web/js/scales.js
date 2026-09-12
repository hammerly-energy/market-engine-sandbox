/* W3.2: the map's price scale. Colour only -- this module maps a number the
 * engine returned onto a hex string, which is the browser picking a colour
 * and not the browser doing market arithmetic. No number here reaches the
 * wire, and no number on screen is computed here.
 *
 * Two decisions are baked in, and both were measured rather than argued.
 *
 * IDENTITY IS GONE FROM THE BUS. A bus used to be an Okabe-Ito hue matching
 * src/viz. It is now a neutral disc with its name inside it and a ring that
 * carries the price. So the map has two coloured marks -- rings and lines --
 * and they must not be confused for one another at any point on either
 * scale.
 *
 * WHICH MEANS THE RING TAKES NO HUE AT ALL. The line ramp runs blue to
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
