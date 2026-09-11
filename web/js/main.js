/* W2.1: the editor's state, on screen, before anything can edit it.
 *
 * Nothing here solves -- transport is W2.2 and the network drawing is W2.3.
 * What this page proves is the seam beneath both: the seed loads, state.js
 * builds editor state from it, and toConfig() emits a body the server's
 * caps accept. A failure at W2.2 is then a failure in transport and not in
 * the state underneath it.
 */

import { ApiError, getLimits } from "./api.js";
import { checkBounds, fetchSeed, stateFromSeed, toConfig, toLimits } from "./state.js";

const status = document.querySelector("#status");

function rows(el, pairs) {
  el.replaceChildren();
  for (const [term, value] of pairs) {
    const dt = document.createElement("dt");
    dt.textContent = term;
    const dd = document.createElement("dd");
    dd.textContent = value;
    el.append(dt, dd);
  }
}

function say(text, state) {
  status.textContent = text;
  if (state) status.dataset.state = state;
  else delete status.dataset.state;
}

try {
  const [caps, seed] = await Promise.all([getLimits(), fetchSeed()]);
  const editor = stateFromSeed(seed);

  rows(document.querySelector("#limits"), [
    ["Buses", `${editor.buses.length} / ${caps.max_buses}`],
    ["Branches", `${Object.keys(editor.branches).length} / ${caps.max_branches}`],
    ["Generators", `${Object.keys(editor.fleet).length} / ${caps.max_generators}`],
    ["Bids", `${Object.keys(editor.bids).length} / ${caps.max_bids}`],
    ["Hours", `${editor.shape.length} / ${caps.max_hours}`],
  ]);

  rows(document.querySelector("#editor"), [
    ["Buses", editor.buses.map((bus) => bus.name).join(", ")],
    ["Slack", editor.slack],
    ["Hour", `${editor.hour + 1} of ${editor.shape.length}`],
    ["Offer cap", `$${editor.offerCap.toLocaleString()}/MWh`],
    ["Limit overrides", Object.keys(editor.limits).length || "none"],
  ]);

  /* The exact body W2.2 will post, shown rather than described. Collapsed,
     because it is a proof and not a view -- the seven views are W3. */
  const body = { config: toConfig(editor), slack: editor.slack, limits: toLimits(editor) };
  const text = JSON.stringify(body, null, 2);
  document.querySelector("#body").textContent = text;
  document.querySelector("#body-summary").textContent =
    `What would be posted (${new TextEncoder().encode(text).length.toLocaleString()} bytes of ${caps.max_body_bytes.toLocaleString()})`;

  const problems = checkBounds(editor, caps);
  if (problems.length > 0) {
    say(problems.map((p) => `${p.code}: ${p.detail}`).join(" — "), "error");
  } else {
    say("Seeded from configs/w1.yaml. Within every cap, not yet posted.");
  }
} catch (err) {
  say(err instanceof ApiError ? `${err.code}: ${err.detail}` : String(err), "error");
}
