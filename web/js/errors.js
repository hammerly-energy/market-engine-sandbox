/* The error surface: one place that turns a failure into something readable.
 *
 * It switches on the code and prints the detail verbatim. `code` is a stable
 * string -- bounds.py calls it exactly that -- so this file may branch on it.
 * `detail` is a sentence written on the server to be read by a person, naming
 * the bus, the count or the cap that was wrong; rewriting it here would throw
 * away the only part that says which thing went wrong.
 *
 *     code    ->  a heading this file chooses, and what to do about it
 *     detail  ->  shown as sent, never parsed, never reworded
 *
 * A code this file does not know still renders: the heading falls back to the
 * code itself and the detail carries the meaning. An unknown code must never
 * be swallowed -- a server that grows a refusal and a page that hides it puts
 * back the silent failure W1 removed.
 */

const KNOWN = {
  /* --------------------------------------------------- the caps (bounds.py) */
  body_too_large: {
    heading: "Scenario too large to post",
    fix: "The network exceeds the server's body cap. Remove some of it.",
  },
  too_many_buses: { heading: "Too many buses", fix: "Remove a bus." },
  too_many_branches: { heading: "Too many branches", fix: "Remove a line." },
  too_many_generators: { heading: "Too many generators", fix: "Remove a unit." },
  too_many_bids: { heading: "Too many bids", fix: "Remove a demand bid." },
  too_many_hours: { heading: "Too many hours", fix: "Shorten the load shape." },

  /* ------------------------------------------- what the engine refuses to price
   *
   * One code covers all of them, because they are one kind of statement: the
   * scenario cannot be built. The detail is the part that differs, and the
   * table in CLAUDE.md is the list: a one-bus network, a duplicate name, a
   * zero reactance, an empty fleet, a slack that is not a bus. A cut network
   * is not among them -- an island is priced, not refused. Those sentences
   * were written to be read and are shown as written.
   */
  invalid_scenario: {
    heading: "The engine will not price this network",
    fix: null,
  },

  /* Reachable over HTTP, not from the editor: toConfig() always emits
     `blocks`. If a visitor sees this, the emitter has been changed and the
     change is the bug -- bounds.py refuses eia930 because a source that
     fetches would make a stranger's POST call a live API with this server's
     key. */
  unsupported_load_source: {
    heading: "That demand source cannot be reached over HTTP",
    fix: "The editor declares its demand as priced blocks. This is a client bug.",
  },

  /* An LP that did not reach optimal. After W1 the reachable case is
     inelastic load the fleet cannot serve -- and the editor emits only
     `blocks`, so a visitor should never see this. If one does, it is a bug in
     the editor's config emitter and not a market result. */
  solve_failed: {
    heading: "The market did not clear",
    fix: "This should be unreachable from the editor. It is a bug, not a price.",
  },

  /* ---------------------------------------------------------- transport */
  malformed_json: {
    heading: "The server could not read the request",
    fix: "This is a client bug: the editor sent a body it cannot have meant.",
  },
  unreachable: {
    heading: "No answer from the server",
    fix: "The solver process is not responding. Nothing on screen has been re-solved.",
  },
  unreadable_response: {
    heading: "The server answered with something unreadable",
    fix: null,
  },
  client_error: {
    heading: "The editor failed before the server answered",
    fix: "This is a bug in the page, not a statement about the network.",
  },
  unknown_error: { heading: "The server refused the request", fix: null },
};

/* An ApiError, or anything else, as {code, heading, detail, fix}.

   `fix` is a sentence about what a visitor can DO, and it is null wherever
   there is nothing honest to say -- an empty gesture at a fix is worse than
   none, because it implies the detail was not already the instruction. */
export function describe(err) {
  const code = err?.code ?? "client_error";
  const detail = err?.detail ?? String(err?.message ?? err);
  const known = KNOWN[code] ?? { heading: code, fix: null };
  return { code, heading: known.heading, detail, fix: known.fix };
}

/* The one line a status strip shows: heading, then the server's own sentence.
   Kept as a function rather than a template at each call site so every place
   that reports a failure reports it the same way. */
export function summarize(err) {
  const { heading, detail } = describe(err);
  return `${heading} — ${detail}`;
}
