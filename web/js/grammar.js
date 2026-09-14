/* W2.5: the editing grammar.
 *
 * Drag moves a bus. Every other structural edit is an armed mode -- press a
 * button, then click the target. No modifier keys, no right-click, no
 * keyboard shortcuts. One grammar, and the same one for adding and removing
 * (CLAUDE.md, W2 decision: the editing grammar).
 *
 *     idle  ──press a button──>  armed  ──click a target──>  applied, idle
 *      ▲                           │
 *      └──── Esc, or press the ────┘
 *            armed button again
 *
 * With drag reserved for moving, a bus is never a drop target, so
 * hit-testing only has to answer
 * "which mark is under the pointer". There is no drag-source/drop-target
 * distinction, no rubber-band line to hit-test against, and no geometry in
 * this file at all beyond one coordinate conversion: every mark is a real SVG
 * element carrying a data- attribute, so `closest()` is the hit test. That is
 * most of what the ladder flags as this phase's overrun risk, removed by the
 * grammar rather than by hit-test geometry.
 *
 * Three things ride along because they are the same hit-testing and the same
 * state object:
 *
 *   the armed-state readout   a mode that is armed and invisible is how a
 *                             visitor who armed "connect", got distracted and
 *                             came back connects two buses they had stopped
 *                             thinking about
 *   the keyboard path         focus and activate, not a shortcut. Marks are
 *                             focusable and Enter completes the armed mode --
 *                             the ordinary activation semantics a button
 *                             already has, extended to the click half of the
 *                             grammar. Without it this phase ships a page
 *                             where every slider is keyboard-operable and no
 *                             structural edit is
 *   undo                      pulled forward, and it is what makes Remove
 *                             safe rather than a confirmation step
 *
 * No market arithmetic. This file reads pointer coordinates and writes
 * declarations. Every number it produces is a bus coordinate, and coordinates
 * are editor state that never cross the wire.
 */

import {
  addBus,
  addGenerator,
  connect,
  cut,
  moveBus,
  placementFor,
  removeBus,
  removeGenerator,
} from "./edits.js";

/* ------------------------------------------------------------------ modes
 *
 * `takes` is what a mode will act on, and it is the whole hit test: a click
 * on anything else in that mode is not an edit, and says so rather than
 * doing nothing. "ground" is the empty field of the figure, which is a
 * target for exactly one mode.
 */
export const MODES = [
  {
    id: "move",
    label: "Move Bus",
    verb: "Move",
    takes: [],
    hint: "Drag a bus to move it. Coordinates never cross the wire.",
  },
  {
    id: "add-bus",
    label: "+ Bus",
    verb: "Add bus",
    takes: ["ground"],
    hint: "Click empty ground to place a bus. It gets no generator and no bid.",
  },
  {
    id: "connect",
    label: "+ Line",
    verb: "Add line",
    takes: ["bus"],
    hint: "Click one bus, then another. The new line is unrated.",
  },
  {
    id: "add-generator",
    label: "+ Generator",
    verb: "Add generator",
    /* The one button that carries a mark. It draws the same square the map
       draws, so "press this, then click a bus" and "that square is what
       appeared" are visibly the same object -- which is the only thing
       standing in for a generator's name, since the marks are unlabelled. */
    mark: "unit",
    takes: ["bus"],
    hint: "Click a bus to put a 100 MW unit on it, offered at $25/MWh.",
  },
  {
    id: "remove",
    label: "Remove Item",
    verb: "Remove",
    takes: ["bus", "branch", "generator"],
    hint: "Click a bus, a line or a generator. Undo puts it back.",
  },
];

const MODE = new Map(MODES.map((m) => [m.id, m]));
const IDLE = "move";

/* How far the pointer may travel and still count as a click rather than a
   drag, in SVG user units scaled to the figure. A bus disc is 14 units, so
   this is comfortably inside one. */
const DRAG_SLOP = 3;

/* ------------------------------------------------------------- hit testing
 *
 * Every mark render.js draws carries its own data- attribute, so the target
 * of an event is the answer -- no geometry, no distance search, no z-order
 * reasoning. The transparent `.hit` shapes render.js lays over each mark are
 * what make a 14-unit disc and a 1.6-unit line comfortable to hit; they are a
 * matter of pointer comfort and carry no meaning of their own.
 */
function markAt(node) {
  const el = node?.closest?.("[data-bus], [data-branch], [data-gen]");
  if (!el) return { kind: "ground" };
  if (el.dataset.bus !== undefined) return { kind: "bus", name: el.dataset.bus, el };
  if (el.dataset.branch !== undefined) return { kind: "branch", name: el.dataset.branch, el };
  return { kind: "generator", name: el.dataset.gen, el };
}

/* Client pixels to viewBox user units. The viewBox is the editor's field and
   is fixed (render.js), so this is one scale -- but it is still read from the
   CTM rather than computed, because the figure's rendered width is not. */
function pointIn(svg, event) {
  const ctm = svg.getScreenCTM();
  if (!ctm) return { x: 0, y: 0 };
  const p = new DOMPoint(event.clientX, event.clientY).matrixTransform(ctm.inverse());
  return { x: p.x, y: p.y };
}

/* ------------------------------------------------------------------ mount
 *
 * mountGrammar({svg, toolbar, readout, state, edit, move, mark, undo})
 *
 *   edit(label, mutator)   a structural change. main.js marks undo, mutates,
 *                          rebuilds the levers and posts a solve.
 *   move(mutator)          a coordinate change. Redraw only -- there is
 *                          nothing to ask the engine, because coordinates are
 *                          not on the wire.
 *   mark(label)            record an undo point without mutating, which is
 *                          what a drag needs: one point for the whole drag,
 *                          taken before the first pointermove.
 *   drop()                 throw the newest mark away. A press that never
 *                          moved was a click, not a drag, and its mark
 *                          describes an edit that did not happen.
 *   undo()                 pop one; returns a label or null.
 *
 * Returns {refresh} -- redraws the toolbar and readout from the current mode,
 * for callers that rebuilt the DOM underneath it.
 */
export function mountGrammar({ svg, toolbar, undoSlot, readout, state, edit, move, mark, drop, undo }) {
  let mode = IDLE;
  let pending = null; // the first bus of a connect, between its two clicks
  let drag = null;

  /* ------------------------------------------------------------- the view */

  const buttons = new Map();
  toolbar.replaceChildren();
  for (const m of MODES) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.mode = m.id;
    button.append(document.createTextNode(m.label));
    if (m.mark === "unit") {
      /* An inline SVG square, not a glyph: it is the mark on the map, drawn
         the same way, so the two cannot drift to different shapes. Marked
         aria-hidden -- the label already says "generator", and a screen
         reader announcing a decorative square would say it twice. */
      const NS_SVG = "http://www.w3.org/2000/svg";
      const icon = document.createElementNS(NS_SVG, "svg");
      icon.setAttribute("viewBox", "0 0 10 10");
      icon.setAttribute("class", "button-mark");
      icon.setAttribute("aria-hidden", "true");
      const square = document.createElementNS(NS_SVG, "rect");
      square.setAttribute("x", "1.5");
      square.setAttribute("y", "1.5");
      square.setAttribute("width", "7");
      square.setAttribute("height", "7");
      icon.append(square);
      button.append(icon);
    }
    button.setAttribute("aria-pressed", "false");
    /* Pressing the armed button again disarms, which is the same gesture as
       Esc and is why this is a toggle rather than a radio group. */
    button.addEventListener("click", () => arm(mode === m.id ? IDLE : m.id));
    buttons.set(m.id, button);
    toolbar.append(button);
  }

  /* Undo is not a sixth mode, and it does not live in the group of five. It
     sits beside the readout, which is the line that says what just happened
     -- so "that is what happened" and "put it back" are next to each other,
     and nothing in the armed group can be misread as a thing to arm. It is
     also what keeps the five modes on one row at the figure's width. */
  const undoButton = document.createElement("button");
  undoButton.type = "button";
  undoButton.textContent = "Undo";
  undoButton.className = "undo";
  undoButton.addEventListener("click", () => {
    const label = undo();
    say(label ? `Undone: ${label}.` : "Nothing to undo.");
  });
  undoSlot.replaceChildren(undoButton);

  /* The armed-state readout. An armed mode must be visible in three places at
     once -- the pressed button, the cursor, and this sentence -- because each
     one is missable on its own. */
  function say(extra = null) {
    const m = MODE.get(mode);
    /* The prose uses `verb`, not `label`. A button label is shaped to be read
       at a glance on a chip -- "+ Line" -- and a sentence built from it reads
       as punctuation ("+ Line armed."). The two are separate fields so the
       toolbar can be terse without the readout becoming unreadable. */
    const armed =
      mode === IDLE
        ? "Move mode."
        : pending
          ? `Add line armed, from ${pending}.`
          : `${m.verb} armed.`;
    readout.textContent = [armed, extra ?? m.hint].join(" ");
    readout.dataset.mode = mode;
  }

  /* Arming, disarming, and the return to idle after an applied edit are one
     function, because the diagram above has one arrow into idle and splitting
     it is how a mode ends up left armed on one path and not another. The
     optional message is what the edit did; without one the mode's own hint
     stands. */
  function arm(next, message = null) {
    mode = next;
    pending = null;
    for (const [id, button] of buttons) {
      button.setAttribute("aria-pressed", String(id === mode));
    }
    svg.dataset.mode = mode;
    highlight();
    say(message);
  }

  /* The pending first bus of a connect, marked on the mark itself. It lives
     between two clicks with no re-render in between -- nothing in state has
     changed yet -- so an attribute is enough and survives until the second
     click redraws everything. */
  function highlight() {
    for (const el of svg.querySelectorAll("[data-pending]")) delete el.dataset.pending;
    if (!pending) return;
    const el = svg.querySelector(`[data-bus="${CSS.escape(pending)}"]`);
    if (el) el.dataset.pending = "true";
  }

  /* ----------------------------------------------------------- activation
   *
   * One function for the click half of the grammar, whether the click came
   * from a pointer or from Enter on a focused mark. That is what keeps the
   * keyboard path a path rather than a parallel implementation that drifts.
   */
  function activate(hit, ground) {
    const m = MODE.get(mode);

    if (mode === IDLE) return;

    if (!m.takes.includes(hit.kind)) {
      say(`Nothing to do — ${m.verb.toLowerCase()} acts on a ${m.takes.join(", a ")}.`);
      return;
    }

    /* An applied edit returns to idle. That is the diagram's one arrow back,
       and it is what stops a mode outliving the act it was armed for -- the
       distracted-visitor failure the readout exists to make visible. The
       message replaces the next mode's hint, so the page says what happened
       rather than what could happen next. */
    let said = null;
    const done = (mutator) => (s) => {
      said = mutator(s);
    };

    if (mode === "add-bus") {
      edit("add a bus", done((s) => {
        const name = addBus(s, ground.x, ground.y);
        return `Added bus ${name}. It has no generator and no bid.`;
      }));
      arm(IDLE, said);
      return;
    }

    if (mode === "add-generator") {
      edit(`add a generator at ${hit.name}`, done((s) => {
        const name = addGenerator(s, hit.name);
        return `Added ${name} at ${hit.name}, 100 MW at $25.00/MWh.`;
      }));
      arm(IDLE, said);
      return;
    }

    if (mode === "connect") {
      if (!pending) {
        pending = hit.name;
        highlight();
        say(`Click a second bus to connect it to ${pending}.`);
        return;
      }
      const from = pending;
      if (from === hit.name) {
        pending = null;
        highlight();
        say(`${from} cannot connect to itself — a self-loop carries no flow.`);
        return;
      }
      edit(`connect ${from} to ${hit.name}`, done((s) => {
        const name = connect(s, from, hit.name);
        return `Added line ${name}, unrated. Its rating is a lever below.`;
      }));
      arm(IDLE, said);
      return;
    }

    if (mode === "remove") {
      if (hit.kind === "bus") {
        edit(`remove bus ${hit.name}`, done((s) => {
          const wasSlack = s.slack === hit.name;
          removeBus(s, hit.name);
          return (
            `Removed bus ${hit.name}, with the lines, units and bids that named it.` +
            (wasSlack && s.slack !== hit.name ? ` The slack moved to ${s.slack}.` : "")
          );
        }));
      } else if (hit.kind === "branch") {
        edit(`cut line ${hit.name}`, done((s) => {
          cut(s, hit.name);
          return `Cut line ${hit.name}. If that split the network, each island is priced on its own.`;
        }));
      } else {
        edit(`remove generator ${hit.name}`, done((s) => {
          removeGenerator(s, hit.name);
          return `Removed generator ${hit.name}.`;
        }));
      }
      arm(IDLE, said);
      return;
    }
  }

  /* --------------------------------------------------------------- pointer
   *
   * pointerdown decides between a drag and a click; pointerup with no
   * meaningful travel is the click. Drag is live -- the map must not wait for
   * a solve, and here there is not even one to wait for.
   */
  svg.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const hit = markAt(event.target);

    if (mode === IDLE && hit.kind === "bus") {
      const at = pointIn(svg, event);
      const bus = state.buses.find((b) => b.name === hit.name);
      drag = { name: hit.name, dx: bus.x - at.x, dy: bus.y - at.y, moved: false };
      /* One undo point for the whole drag, taken before the first move --
         otherwise a drag across the panel would leave a hundred of them and
         undo would walk the pointer back a pixel at a time. */
      mark(`move bus ${hit.name}`);
      // Capture so a fast drag that outruns the disc keeps sending moves
      // here. Guarded: a synthetic event carries a pointerId the browser
      // never issued, and a throw would take the whole handler with it.
      try {
        svg.setPointerCapture(event.pointerId);
      } catch {
        /* not a real pointer; the drag still works without capture */
      }
      event.preventDefault();
    }
  });

  svg.addEventListener("pointermove", (event) => {
    if (!drag) return;
    const at = pointIn(svg, event);
    const x = at.x + drag.dx;
    const y = at.y + drag.dy;
    const bus = state.buses.find((b) => b.name === drag.name);
    if (!drag.moved && Math.hypot(x - bus.x, y - bus.y) < DRAG_SLOP) return;
    drag.moved = true;
    move((s) => moveBus(s, drag.name, x, y));
  });

  svg.addEventListener("pointerup", (event) => {
    if (drag) {
      const { name, moved: wasDrag } = drag;
      drag = null;
      try {
        if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
      } catch {
        /* never captured; nothing to release */
      }
      /* A press that never moved is a click, not a drag, so the undo point
         taken on pointerdown describes an edit that did not happen. Dropped
         rather than undone: undoing would restore an identical state and
         re-solve for it. */
      if (!wasDrag) drop();
      if (wasDrag) {
        say(`Moved bus ${name}. No solve — a coordinate is not on the wire.`);
        return;
      }
    }
    activate(markAt(event.target), pointIn(svg, event));
  });

  /* --------------------------------------------------------------- keyboard
   *
   * Focus and activate. Enter or Space on a focused mark does exactly what a
   * click on it does, and Esc disarms -- the same two gestures a button
   * already has. Nothing here is a shortcut: no key arms a mode, and no key
   * does anything a pointer could not.
   *
   * Add-bus is the one mode with no mark to focus, because empty ground is
   * not a thing that can hold focus. So Enter on the figure itself places one
   * at a computed point (edits.placementFor) and the visitor drags it where
   * they want. A coordinate is not a market quantity, so nothing is lost by
   * the editor choosing the first one.
   */
  svg.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      arm(IDLE);
      event.preventDefault();
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") return;
    if (mode === IDLE) return;

    const hit = markAt(event.target);
    const ground = hit.kind === "ground" ? placementFor(state) : { x: 0, y: 0 };
    activate(hit, ground);
    event.preventDefault();
  });

  arm(IDLE);
  return {
    refresh() {
      highlight();
      say();
    },
    mode: () => mode,
  };
}
