/* W2.3: the state of W2.1, posted over the transport of W2.2, and DRAWN.
 *
 * What lands here is the minimum that proves a lever worked -- the network,
 * LMP per bus, lambda per island, the settlement residual -- and no more.
 * The seven views are W3. The traffic log below stays because it is W2.2's
 * evidence: which request ids were issued, which one was applied, which were
 * dropped as superseded, and what the failure surface says when the server
 * refuses. A rendering built on top of an untrustworthy transport would make
 * every transport bug look like a rendering bug.
 *
 * No number below is computed. Everything shown is a field of the clear()
 * return, counted or formatted -- the boundary rule.
 *
 *     editor state ----> renderNetwork      topology, drawn immediately
 *          |
 *        submit() --> solve --> cleared --> renderPrices, renderIslands
 *                        \                  markStale(false)
 *                         \--> error/stale -> markStale(true), numbers kept
 */

import { bodyFor, createSolver, getLimits } from "./api.js";
import { describe, summarize } from "./errors.js";
import { checkBounds, fetchSeed, stateFromSeed } from "./state.js";
import { markStale, renderIslands, renderNetwork, renderPrices } from "./render.js";

const status = document.querySelector("#status");
const log = document.querySelector("#log");

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

function note(id, text, state) {
  const li = document.createElement("li");
  li.textContent = `#${id} ${text}`;
  if (state) li.dataset.state = state;
  log.prepend(li);
}

const editor = stateFromSeed(await fetchSeed());
let caps = null;

const solve = createSolver({
  onPending: (id) => note(id, "posted"),
});

/* One place that turns an outcome into what is on screen. Every lever at
   W2.4 and after calls this and nothing else, so "a solve happened" and
   "the page changed" cannot drift apart. */
async function submit() {
  /* The client-side bound check, before the post. A courtesy: bounds.py is
     the defence and does not trust this to have run. */
  const problems = caps ? checkBounds(editor, caps) : [];
  if (problems.length > 0) {
    say(summarize(problems[0]), "error");
    note("—", `refused before posting: ${problems[0].code}`, "error");
    return;
  }

  const outcome = await solve(editor);

  if (outcome.status === "superseded") {
    /* Not a failure. A newer request already landed, so this answer is about
       a network the visitor has edited away from. Dropped, and said so --
       the drop is visible here because this phase is about the drop. The
       readouts are NOT marked stale: a fresher answer is already applied or
       on its way, and flickering "stale" through a drag would cry wolf. */
    note(outcome.id, "superseded, dropped", "muted");
    return;
  }

  if (outcome.status === "error") {
    const { code, heading, detail, fix } = describe(outcome.error);
    say([heading, "—", detail, fix].filter(Boolean).join(" "), "error");
    note(outcome.id, `refused: ${code}`, "error");
    /* The map has moved and the prices have not. Kept and marked, not
       cleared: a blank table reads as "no prices exist", which is a
       different and false claim. */
    markStale(true);
    return;
  }

  const cleared = outcome.result;
  note(outcome.id, "applied", "ok");

  /* The hour the editor is on indexes every returned array. The day comes
     back whole, so moving the hour (W2.4) re-reads these and does not
     re-solve. Guarded because the editor can hold an hour past the end of a
     shape it has since shortened. */
  const hour = Math.min(editor.hour, cleared.hours.length - 1);

  renderPrices(
    document.querySelector("#prices"),
    cleared,
    hour,
    editor.buses.map((bus) => bus.name),
  );
  renderIslands(document.querySelector("#islands"), cleared, hour);
  markStale(false);

  say(
    `Cleared hour ${hour + 1} of ${cleared.hours.length}. ` +
      `${cleared.buses.length} buses, ${cleared.lines.length} lines, ` +
      `${Object.keys(cleared.islands).length} island(s), slack ${cleared.slack}.`,
  );
}

try {
  caps = await getLimits();
  rows(document.querySelector("#limits"), [
    ["Buses", `${editor.buses.length} / ${caps.max_buses}`],
    ["Branches", `${Object.keys(editor.branches).length} / ${caps.max_branches}`],
    ["Generators", `${Object.keys(editor.fleet).length} / ${caps.max_generators}`],
    ["Bids", `${Object.keys(editor.bids).length} / ${caps.max_bids}`],
    ["Hours", `${editor.shape.length} / ${caps.max_hours}`],
  ]);
} catch (err) {
  say(summarize(err), "error");
}

/* Drawn from editor state, before anything is posted. Topology does not wait
   for a solve -- see render.js. W2.5's drags will call this on every move. */
renderNetwork(document.querySelector("#network"), editor);

rows(document.querySelector("#editor"), [
  ["Buses", editor.buses.map((bus) => bus.name).join(", ")],
  ["Slack", editor.slack],
  ["Hour", `${editor.hour + 1} of ${editor.shape.length}`],
  ["Offer cap", `$${editor.offerCap.toLocaleString()}/MWh`],
  ["Limit overrides", Object.keys(editor.limits).length || "none"],
]);

const text = JSON.stringify(bodyFor(editor), null, 2);
document.querySelector("#body").textContent = text;
document.querySelector("#body-summary").textContent =
  `What is posted (${new TextEncoder().encode(text).length.toLocaleString()} bytes` +
  (caps ? ` of ${caps.max_body_bytes.toLocaleString()}` : "") +
  ")";

document.querySelector("#solve").addEventListener("click", () => submit());

/* Five posts in one tick, which is what a drag looks like to this module.
   Exactly one is applied and the rest are dropped -- and the point is that
   the one applied is the LAST ISSUED, not the first returned. */
document.querySelector("#burst").addEventListener("click", () => {
  for (let i = 0; i < 5; i += 1) submit();
});

await submit();
