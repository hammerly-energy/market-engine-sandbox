/* W2.4: the five non-drag levers, against the live engine.
 *
 * The split this phase adds:
 *
 *     four levers change the scenario -> solve() -> paint()
 *     the hour lever changes the view  ->            paint()
 *
 * clear() returns the whole day. Every series is one array per name aligned
 * to `hours`, so the hour is an index into an answer that is already in the
 * browser -- posting for it would be a second answer to a question already
 * answered, and at a degenerate breakpoint the two could differ (trap 3) with
 * nothing on screen to explain why. So paint() is the only thing that writes
 * to the page, solve() is the only thing that talks to the server, and the
 * hour calls one of them.
 *
 *     editor state --> renderNetwork                   drawn at once
 *          |
 *        solve() --> cleared --------> paint(hour)      prices, islands
 *          |    \--> error/stale ----> markStale(true)  numbers kept
 *          |
 *        paint() reads `cleared`, never the server
 *
 * W2.5 adds a third kind of change, and this module is where the three are
 * told apart, because that is the only place they can be:
 *
 *     structural  add/remove a bus, a line, a generator. The shape of the
 *                 scenario moved, so the levers are rebuilt too -- a removed
 *                 generator whose sliders stayed would write into an object
 *                 nothing renders. Undo point, redraw, re-solve.
 *     a lever     a number moved. Redraw, re-solve, levers left alone (they
 *                 are being dragged).
 *     a drag      a coordinate moved. Redraw and nothing else: coordinates are
 *                 editor state, never cross the wire, and no price depends on
 *                 them, so a solve here would be a round trip for an answer
 *                 the browser already has.
 *
 * No number below is computed. Everything shown is a field of the clear()
 * return, counted or formatted -- the boundary rule.
 */

import { bodyFor, createSolver, getLimits } from "./api.js";
import { mountHour, mountLevers, pausePlayback } from "./controls.js";
import { createHistory } from "./edits.js";
import { describe, summarize } from "./errors.js";
import { renderFlows } from "./flows.js";
import { mountGrammar } from "./grammar.js";
import { mountTimelinePicker, renderTimeline } from "./timeline.js";
import { renderMerit } from "./merit.js";
import { peakHour } from "./scales.js";
import { checkBounds, fetchSeed, stateFromSeed } from "./state.js";
import { renderUnits } from "./units.js";
import {
  markStale,
  renderIslands,
  renderNetwork,
  renderSplit,
} from "./render.js";

const status = document.querySelector("#status");
const log = document.querySelector("#log");

/* The log is evidence, not a view, and a drag writes to it a hundred times a
   second. Trimmed so it stays readable rather than becoming the page. */
const LOG_KEPT = 60;

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
  while (log.children.length > LOG_KEPT) log.lastElementChild.remove();
}

const editor = stateFromSeed(await fetchSeed());
let caps = null;

/* Whether an answer has ever landed. It gates the opening hour, which is
   picked from the first solve and left alone after it. */
let opened = false;

/* The last answer that was applied. paint() reads this and nothing else, so
   moving the hour cannot reach the server and cannot invent a number. Null
   until the first solve lands, which is why paint() can be called before
   there is anything to paint. */
let cleared = null;

const solve = createSolver({
  onPending: (id) => note(id, "posted"),
});

/* ------------------------------------------------------------------ paint */

/* Everything the hour indexes. Reads `cleared`, never the network.
 *
 * The hour is clamped rather than trusted: the editor can hold an hour past
 * the end of a shape it has since shortened, and an out-of-range index would
 * print `undefined` where a price belongs. */
function paint() {
  refreshReadouts();
  if (!cleared) return;
  const hour = Math.min(editor.hour, cleared.hours.length - 1);

  /* W3.2 put prices on the map, so the hour redraws it. It still does not
     re-solve: the hour indexes a day already in the browser, and the ring
     colours come out of the same arrays the table below reads. */
  draw();

  renderSplit(
    document.querySelector("#split"),
    cleared,
    hour,
    editor.buses.map((bus) => bus.name),
  );
  renderMerit(document.querySelector("#merit"), cleared, hour);
  /* The branches are passed for their direction only -- which bus is "from"
     and which is "to", so the panel can say which way a positive flow goes.
     Every number in the view is the engine's. */
  renderFlows(document.querySelector("#flows"), cleared, hour, editor.branches);
  renderUnits(document.querySelector("#units"), cleared, hour);
  renderIslands(document.querySelector("#islands"), cleared, hour);
  /* The Timeline's field, which is the hour slider's scale as well as a view.
     The hour is passed so the field can mark the column the thumb is on and
     every other view is showing. */
  renderTimeline(
    document.querySelector("#timeline"),
    cleared,
    hour,
    editor.buses.map((bus) => bus.name),
  );

  document.querySelector("#hour-note").textContent =
    `Hour ${hour + 1} of ${cleared.hours.length}. The whole day came back ` +
    `with the last solve.`;
}

/* The three panels that describe the editor rather than the market: what it
   holds, how it stands against the caps, and the exact body it would post. */
function refreshReadouts() {
  rows(document.querySelector("#editor"), [
    ["Buses", editor.buses.map((bus) => bus.name).join(", ")],
    ["Slack", editor.slack],
    ["Hour", `${editor.hour + 1} of ${editor.shape.length}`],
    ["Offer cap", `$${editor.offerCap.toLocaleString()}/MWh`],
    ["Limit overrides", Object.keys(editor.limits).length || "none"],
  ]);

  if (caps) {
    rows(document.querySelector("#limits"), [
      ["Buses", `${editor.buses.length} / ${caps.max_buses}`],
      ["Branches", `${Object.keys(editor.branches).length} / ${caps.max_branches}`],
      ["Generators", `${Object.keys(editor.fleet).length} / ${caps.max_generators}`],
      ["Bids", `${Object.keys(editor.bids).length} / ${caps.max_bids}`],
      ["Hours", `${editor.shape.length} / ${caps.max_hours}`],
    ]);
  }

  const text = JSON.stringify(bodyFor(editor), null, 2);
  document.querySelector("#body").textContent = text;
  document.querySelector("#body-summary").textContent =
    `What Is Posted (${new TextEncoder().encode(text).length.toLocaleString()} bytes` +
    (caps ? ` of ${caps.max_body_bytes.toLocaleString()}` : "") +
    ")";
}

/* ------------------------------------------------------------------ solve */

/* One place that turns an outcome into what is on screen. Every scenario
   lever calls this and nothing else, so "a solve happened" and "the page
   changed" cannot drift apart. */
async function submit() {
  /* The client-side bound check, before the post. A courtesy: bounds.py is
     the defence and does not trust this to have run. */
  const problems = caps ? checkBounds(editor, caps) : [];
  if (problems.length > 0) {
    say(summarize(problems[0]), "error");
    note("—", `refused before posting: ${problems[0].code}`, "error");
    markStale(true);
    return;
  }

  const outcome = await solve(editor);

  if (outcome.status === "superseded") {
    /* Not a failure. A newer request already landed, so this answer is about
       a network the visitor has edited away from. Dropped, and said so. The
       readouts are NOT marked stale: a fresher answer is already applied or
       on its way, and flickering "stale" through a drag would cry wolf. */
    note(outcome.id, "superseded, dropped", "muted");
    return;
  }

  if (outcome.status === "error") {
    const { code, heading, detail, fix } = describe(outcome.error);
    say([heading, "—", detail, fix].filter(Boolean).join(" "), "error");
    note(outcome.id, `refused: ${code}`, "error");
    /* The levers have moved and the prices have not. Kept and marked, not
       cleared: a blank table reads as "no prices exist", which is a
       different and false claim. */
    markStale(true);
    return;
  }

  note(outcome.id, "applied", "ok");
  cleared = outcome.result;
  markStale(false);

  /* The opening hour, and only the opening one. The seed cannot know where
     the day peaks -- that is an answer, so it is chosen from the first
     answer and never again. Re-running it on every solve would move the hour
     under a hand that is dragging a lever, and the hour is the visitor's
     from the moment the page has one. */
  if (!opened) {
    opened = true;
    const peak = peakHour(cleared);
    if (peak !== null) {
      editor.hour = peak;
      syncHour();
    }
  }

  paint();

  const islands = Object.keys(cleared.islands).length;
  say(
    `Cleared ${cleared.hours.length} hours. ` +
      `${cleared.buses.length} buses, ${cleared.lines.length} lines, ` +
      `${islands} island${islands === 1 ? "" : "s"}, slack ${cleared.slack}.`,
  );
}

/* --------------------------------------------------------------- the wiring
 *
 * A scenario lever redraws the map immediately and posts; the map must not
 * wait a round trip or the editor lags the hand. A view lever paints. That is
 * the entire difference between the two handlers. */
/* The map is drawn from editor state and priced from the last answer. Those
   are two different clocks on purpose: a drag redraws at once, because a map
   that waited a round trip would lag the hand, while the prices on it are
   whatever the last solve said and go visibly stale when one is refused. */
function draw() {
  const hour = cleared ? Math.min(editor.hour, cleared.hours.length - 1) : 0;
  renderNetwork(document.querySelector("#network"), editor, cleared, hour);
}

function onEdit() {
  draw();
  refreshReadouts();
  submit();
}

function onHour() {
  paint();
}

/* W3.11. The Timeline's click, which is its own slider reached through the
 * field instead of through the thumb.
 *
 * It is one hour, held in one place. The pick writes state.hour and then
 * syncs the slider, so the thumb moves to the column that was clicked --
 * backwards, the two halves of one panel would disagree about which hour
 * this is. There is no solve: the hour indexes a day the browser already
 * has, which is the whole reason the slider does not post either.
 *
 * Playback stops, for the same reason dragging the slider stops it. A pick
 * that left the timer running would move the cursor to the clicked hour and
 * then walk it off within 400 ms, so the click would read as not having
 * worked.
 */
function pickHour(h) {
  if (!cleared) return;
  pausePlayback();
  editor.hour = Math.min(Math.max(h, 0), cleared.hours.length - 1);
  syncHour();
  paint();
}

/* ------------------------------------------------------- the three changes
 *
 * A structural edit rebuilds the levers; a lever move does not. Backwards,
 * that is either a slider that jumps out from under a dragging thumb or a
 * slider left pointing at a generator that no longer exists.
 */

const history = createHistory(editor);

/* The hour slider's sync, held because the field's pick moves the hour
   without touching the thumb, and a thumb left where it was would be one
   half of the Timeline disagreeing with the other. Replaced on every
   rebuild; a structural edit throws the old control away. */
let syncHour = () => {};

function rebuild() {
  draw();
  /* Two mounts, because the hour is in the Timeline panel and the other six
     levers are in the rail below it. Both are rebuilt together: a shorter
     shape moves the slider's own maximum, and a removed generator leaves a
     lever writing into an object nothing renders. */
  syncHour = mountHour(document.querySelector("#hour"), editor, { onHour });
  mountLevers(document.querySelector("#levers"), editor, { onEdit });
  refreshReadouts();
}

function structural(label, mutate) {
  history.mark(label);
  mutate(editor);
  rebuild();
  submit();
}

/* A coordinate change. No solve: bus x/y is editor state and never crosses
   the wire, so there is no question here for the engine to answer. Redraw
   only, and it has to be immediate -- a map that waited on anything would lag
   the hand and the editor would feel broken. */
function moved(mutate) {
  mutate(editor);
  draw();
}

function undo() {
  const label = history.undo();
  if (label) {
    rebuild();
    submit();
  }
  return label;
}

try {
  caps = await getLimits();
} catch (err) {
  say(summarize(err), "error");
}

rebuild();

mountGrammar({
  svg: document.querySelector("#network"),
  toolbar: document.querySelector("#toolbar"),
  undoSlot: document.querySelector("#undo-slot"),
  readout: document.querySelector("#armed"),
  state: editor,
  edit: structural,
  move: moved,
  mark: (label) => history.mark(label),
  drop: () => history.drop(),
  undo,
});

/* Mounted once, outside rebuild(): the panel survives every repaint, and a
   listener added per paint would stack one pick per paint. */
mountTimelinePicker(document.querySelector("#timeline"), pickHour);

document.querySelector("#solve").addEventListener("click", () => submit());

/* Five posts in one tick, which is what a drag looks like to this module.
   Exactly one is applied and the rest are dropped, and the one applied is the
   last issued, not the first returned. */
document.querySelector("#burst").addEventListener("click", () => {
  for (let i = 0; i < 5; i += 1) submit();
});

await submit();
