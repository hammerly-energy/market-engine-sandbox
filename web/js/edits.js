/* W2.5: the structural edits, as pure functions on editor state.
 *
 * Add or remove a bus, connect or cut a line, add or remove a generator.
 * Nothing here touches the DOM, the server or an event -- grammar.js owns
 * the interaction and main.js owns the redraw, so what an edit means can be
 * read in one place without reading a pointer handler.
 *
 *     grammar.js   which mark was clicked, and in which armed mode
 *     edits.js     what that does to the state object          <- this file
 *     main.js      snapshot, redraw, post
 *
 * The invariant every edit here maintains: the state object is always a thing
 * toConfig() can emit and the engine can read. A removal that left a branch
 * naming a deleted bus, or a limits override naming a deleted branch, would
 * post a body the engine refuses -- clear() rejects an unknown limit key by
 * name -- and the visitor would read an error about a line they had just
 * removed. So removal is transitive, and it is enforced here, not by hoping
 * every call site remembers.
 *
 * One thing is deliberately not repaired: the hue a bus is drawn in. Colour
 * is assigned by config order (render.js, hueFor) to match src/viz, so
 * removing the second of five buses re-colours the three after it. That is
 * self-consistent rather than wrong -- config order is what changed -- and it
 * is a placeholder either way: W3 replaces the bus fill with a price scale.
 * Inventing a stable per-bus colour id here would be a second identity scheme
 * to keep in step with the figures, for a fill that is scheduled to go.
 */

import { defaultBranch, defaultGenerator } from "./state.js";

/* ------------------------------------------------------------------ naming
 *
 * A name is the load-bearing part, the same way CLAUDE.md says a demand bid's
 * is: it is what the wire carries, what an error sentence quotes, and what a
 * later constraint would hang off. So names are generated to be readable and
 * stable, never to be an index -- and never reused, because a name that came
 * back after a removal would make undo and the log describe two different
 * objects with one word.
 */

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/* Buses continue the alphabet case5 started, then fall back to B26, B27...
   rather than doubling letters, because AA next to A and B reads as a
   relationship between them that does not exist. */
export function nextBusName(state) {
  const taken = new Set(state.buses.map((bus) => bus.name));
  for (const letter of LETTERS) if (!taken.has(letter)) return letter;
  for (let n = LETTERS.length; ; n += 1) {
    const name = `B${n}`;
    if (!taken.has(name)) return name;
  }
}

/* Branches are named for their ends, which is what case5 does -- AB, DE. A
   second line between the same pair is physical and is not a collision
   (CLAUDE.md, "not a bug"), so it takes a suffix rather than being refused. */
export function nextBranchName(state, from, to) {
  const taken = new Set(Object.keys(state.branches));
  const base = `${from}${to}`;
  if (!taken.has(base)) return base;
  for (let n = 2; ; n += 1) {
    const name = `${base}${n}`;
    if (!taken.has(name)) return name;
  }
}

/* A generator is named for the bus it sits on and its rank there -- A1, A2,
   C1 -- which is the scheme the branches already use, one mark over.
 *
 * It replaces a global g1, g2 counter. The counter named a unit for the order
 * it was created in, which is a fact about the session and not about the
 * market: delete A2 and add a unit at E, and the old scheme called it g2 and
 * put it next to a bus it had nothing to do with. The map has no room to
 * label a generator square, so the name is the only place a reader learns
 * where a unit is -- and every panel that prints a unit prints this name.
 *
 * Reusing the lowest free rank rather than counting up means adding and
 * removing at one bus does not walk the numbers upward. The name is an
 * identifier and never parsed, so a bus called B26 taking B261 is unique and
 * that is all it has to be. */
export function nextGeneratorName(state, bus) {
  const taken = new Set(Object.keys(state.fleet));
  for (let n = 1; ; n += 1) {
    const name = `${bus}${n}`;
    if (!taken.has(name)) return name;
  }
}

/* ------------------------------------------------------------------- buses */

export function addBus(state, x, y) {
  const name = nextBusName(state);
  state.buses.push({ name, x, y });
  return name;
}

/* Remove a bus and everything that names it.
 *
 * Transitive: a branch to a bus that is gone, a generator at it or a bid on it
 * are each a body the engine refuses by name, and the visitor would read a
 * sentence about an object they did not touch.
 *
 * The slack is kept valid here, which is half of W2.6 arriving early because
 * the alternative is a 422 on the most ordinary edit on the page. The engine
 * refuses a slack that is not a bus and that refusal is correct -- it is the
 * check that catches the editor failing to keep its own dropdown in step
 * (CLAUDE.md, W2.6). So the editor keeps it in step. It moves to the first
 * remaining bus in config order, which is the same rule the engine's own
 * fallback follows, so the two cannot disagree about where it went.
 *
 * With no buses left the slack is left naming the bus it named. There is
 * nothing honest to move it to, and the engine's sentence -- the slack is not
 * a bus in [] -- is a true description of an empty network.
 */
export function removeBus(state, name) {
  state.buses = state.buses.filter((bus) => bus.name !== name);

  for (const [line, br] of Object.entries(state.branches)) {
    if (br.from === name || br.to === name) cut(state, line);
  }
  for (const [gen, spec] of Object.entries(state.fleet)) {
    if (spec.bus === name) delete state.fleet[gen];
  }
  for (const [bid, spec] of Object.entries(state.bids)) {
    if (spec.bus === name) delete state.bids[bid];
  }

  if (state.slack === name && state.buses.length > 0) {
    state.slack = state.buses[0].name;
  }
}

export function moveBus(state, name, x, y) {
  const bus = state.buses.find((b) => b.name === name);
  if (bus) {
    bus.x = x;
    bus.y = y;
  }
}

/* Where the keyboard path puts a bus, since there is no empty ground to
   focus. Deterministic, and stepped by the golden angle so pressing Enter
   three times gives three buses rather than three buses on top of each
   other. Drag moves it afterwards; a coordinate is not a market quantity and
   never crosses the wire. */
export function placementFor(state) {
  if (state.buses.length === 0) return { x: 50, y: 50 };
  const cx = state.buses.reduce((s, b) => s + b.x, 0) / state.buses.length;
  const cy = state.buses.reduce((s, b) => s + b.y, 0) / state.buses.length;
  const reach =
    Math.max(
      ...state.buses.map((b) => Math.hypot(b.x - cx, b.y - cy)),
      20,
    ) * 1.35;
  const angle = state.buses.length * 2.399963; // the golden angle, radians
  return { x: cx + reach * Math.cos(angle), y: cy + reach * Math.sin(angle) };
}

/* ---------------------------------------------------------------- branches */

/* Returns the new branch's name, or null if the pair cannot carry one.
   A self-loop is the only refusal: it has no direction to carry a flow and
   contributes nothing to the susceptance matrix, so it is not a line that
   happens to be useless -- it is not a line. */
export function connect(state, from, to) {
  if (from === to) return null;
  const name = nextBranchName(state, from, to);
  state.branches[name] = defaultBranch(from, to);
  return name;
}

/* Cut a line, and drop its rating override with it.
 *
 * The override is clear()'s limits= argument, keyed by line name, and clear()
 * refuses an unknown key rather than ignoring it. So a cut that left the
 * override behind would make the next solve fail, naming a line the visitor
 * had already removed -- a refusal one edit downstream of its cause, which is
 * the worst kind to debug from a screen.
 */
export function cut(state, line) {
  delete state.branches[line];
  delete state.limits[line];
}

/* -------------------------------------------------------------- generators */

export function addGenerator(state, bus) {
  const name = nextGeneratorName(state, bus);
  state.fleet[name] = defaultGenerator(bus);
  return name;
}

export function removeGenerator(state, name) {
  delete state.fleet[name];
}

export function generatorsAt(fleet, bus) {
  return Object.entries(fleet).filter(([, spec]) => spec.bus === bus);
}

/* ------------------------------------------------------------------- undo
 *
 * Undo is what makes Remove safe, and it replaces a confirmation dialog
 * rather than supplementing one. A confirm taxes the most exploratory act on
 * the page -- and the site's whole pitch is that rewiring is safe to try --
 * while undo removes the class of question instead of answering it each time
 * (CLAUDE.md, W2 decision: the editing grammar).
 *
 * Editor state is plain data, so a snapshot is a structuredClone and the
 * stack is a list of them. Cheaper than the dialog it replaces.
 *
 * Restore writes into the existing object rather than replacing it. The
 * lever closures in controls.js hold references to individual generator and
 * bid objects, so handing back a fresh state object would leave every slider
 * writing into a state nothing renders. Rebuilding the levers after a restore
 * is what re-points them, and main.js does that on every structural edit
 * anyway.
 */

export const MAX_UNDO = 50;

function snapshot(state) {
  return structuredClone(state);
}

function restore(state, snap) {
  for (const key of Object.keys(state)) delete state[key];
  Object.assign(state, structuredClone(snap));
}

/* createHistory(state) -> {mark, undo, drop, depth}
 *
 *   mark(label)  record the state as it is now, before a mutation
 *   undo()       put the most recent mark back; returns its label, or null
 *   drop()       throw the most recent mark away without restoring it
 *   depth()      how many marks are on the stack
 *
 * drop() exists because a drag has to take its undo point on pointerdown --
 * before anything has moved, since after the first pointermove the original
 * position is gone. A press that turns out to be a click rather than a drag
 * therefore leaves a mark describing an edit that never happened. Restoring
 * it would be correct and would also re-solve for nothing; dropping it says
 * the same thing without a round trip.
 */
export function createHistory(state) {
  const stack = [];
  return {
    mark(label) {
      stack.push({ label, state: snapshot(state) });
      if (stack.length > MAX_UNDO) stack.shift();
    },
    undo() {
      const top = stack.pop();
      if (!top) return null;
      restore(state, top.state);
      return top.label;
    },
    drop() {
      return stack.pop() !== undefined;
    },
    depth() {
      return stack.length;
    },
  };
}
