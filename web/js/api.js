/* The only module that talks to the server.
 *
 * Every number this file returns is a field of the clear() return, decoded
 * and nothing else. No market arithmetic happens here or anywhere else in
 * web/ -- see CLAUDE.md, The boundary rule. If a view needs a number the
 * engine does not return, the engine grows; this file does not.
 *
 *   editor state --postClear()--> POST /clear --> the wire body, decoded
 *                      \
 *                       toConfig() / toLimits(), which are state.js's job
 *
 * Errors arrive as {"error": <stable code>, "detail": <a sentence>} with a
 * 4xx. They are thrown as ApiError so a caller can switch on the code and
 * display the detail verbatim -- errors.js is that surface.
 */

import { toConfig, toLimits } from "./state.js";

export class ApiError extends Error {
  constructor(code, detail, status) {
    super(detail);
    this.name = "ApiError";
    this.code = code;
    this.detail = detail;
    this.status = status;
  }
}

async function decode(response) {
  let body;
  try {
    body = await response.json();
  } catch {
    throw new ApiError(
      "unreadable_response",
      `server returned ${response.status} with a body that is not JSON`,
      response.status,
    );
  }
  if (!response.ok) {
    throw new ApiError(
      body.error ?? "unknown_error",
      body.detail ?? `server returned ${response.status}`,
      response.status,
    );
  }
  return body;
}

/* A fetch that failed before there was a response at all -- the process is
   down, the network is gone, the origin refused. It is not a statement about
   the body, so it gets a code of its own rather than borrowing one of the
   server's. An AbortError is NOT this: it is a request this client cancelled
   on purpose, and it is rethrown untouched for the solver to recognise. */
async function send(input, init) {
  try {
    return await fetch(input, init);
  } catch (err) {
    if (err?.name === "AbortError") throw err;
    throw new ApiError("unreachable", `cannot reach the server: ${err.message}`, 0);
  }
}

/* The caps a body must respect, so the editor can refuse before it posts.
   Mirroring them client-side is a courtesy, not the defence: bounds.py is
   the defence, and it rejects rather than truncates. */
export async function getLimits() {
  return decode(await send("/limits"));
}

/* The exact body a state posts. Exported because the page shows it and the
   bound check measures it, and a second place that assembles it is a second
   place for it to be assembled differently. */
export function bodyFor(state) {
  return { config: toConfig(state), slack: state.slack, limits: toLimits(state) };
}

/* Clear, price and settle one scenario.
 *
 * Takes EDITOR STATE, not a hand-built body. The slack goes on the wire
 * explicitly because the editor owns the bus list and owns keeping the two in
 * step; the engine's refusal of a slack that is not a bus is the check that
 * catches it failing to (W2.6).
 */
export async function postClear(state, { signal } = {}) {
  return decode(
    await send("/clear", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(bodyFor(state)),
      signal,
    }),
  );
}

/* ------------------------------------------------------------ coalescing
 *
 * A drag fires many solves and they return out of order, so THE LAST
 * RESPONSE IS NOT THE LAST REQUEST. A solve behind a slider is a live HiGHS
 * call over a network: request n+1 can easily overtake request n on a
 * smaller topology, and a page that renders whatever arrived last will show
 * the prices of a network the visitor has already edited away from -- with
 * no error, and no way to tell from the screen.
 *
 *   issued   1 ───────────────► lands 2nd   dropped, 1 < 3
 *            2 ──────► lands 1st            applied,  2 > 0
 *            3 ──────────► lands 3rd        applied,  3 > 2
 *
 * So every request carries a monotonic id, and a response is applied only if
 * its id beats the highest already applied. Superseded requests are also
 * aborted, which is a courtesy to the server, not the mechanism -- an abort
 * that loses the race still lands as a stale id and is dropped by the same
 * rule.
 *
 * THIS IS NOT DEBOUNCING. Nothing is delayed, coalesced in time, or
 * averaged. Every lever movement still solves, and the price flicker at a
 * degenerate breakpoint is kept and shown -- trap 3, and the single most
 * honest thing this site can demonstrate. What is dropped here is an answer
 * to a question the visitor has already stopped asking, never an answer they
 * would not like.
 */

export const SUPERSEDED = "superseded";

/* Returns solve(state) -> one of
 *
 *   {id, status: "ok",         result}   the freshest answer, apply it
 *   {id, status: "error",      error}    an ApiError, still the freshest
 *   {id, status: SUPERSEDED}             a newer request already landed
 *
 * A result object rather than a thrown error, because "stale" is an outcome
 * and not a failure: a caller that had to catch it would have to tell it
 * apart from a real one, and dropping a render is not an error condition.
 */
export function createSolver({ post = postClear, onPending = null } = {}) {
  let issued = 0;
  let applied = 0;
  let inflight = null;

  return async function solve(state) {
    const id = ++issued;

    if (inflight) inflight.abort();
    const controller = typeof AbortController === "function" ? new AbortController() : null;
    inflight = controller;
    if (onPending) onPending(id);

    let result = null;
    let error = null;
    try {
      result = await post(state, { signal: controller?.signal });
    } catch (err) {
      if (err?.name === "AbortError") return { id, status: SUPERSEDED };
      if (!(err instanceof ApiError)) {
        // A bug in this client, not a statement about the body. It is given a
        // code so the one error surface can render it, and it is not silently
        // relabelled as something the server said.
        err = new ApiError("client_error", String(err?.message ?? err), 0);
      }
      error = err;
    }

    // Checked AFTER the await and after the catch, so the two paths cannot
    // disagree about which request won.
    if (id <= applied) return { id, status: SUPERSEDED };
    applied = id;
    if (inflight === controller) inflight = null;

    return error ? { id, status: "error", error } : { id, status: "ok", result };
  };
}
