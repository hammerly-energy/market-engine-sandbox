/* The only module that talks to the server.
 *
 * Every number this file returns is a field of the clear() return, decoded
 * and nothing else. No market arithmetic happens here or anywhere else in
 * web/ -- see CLAUDE.md, The boundary rule. If a view needs a number the
 * engine does not return, the engine grows; this file does not.
 *
 * Errors arrive as {"error": <stable code>, "detail": <a sentence>} with a
 * 4xx. They are thrown as ApiError so a caller can switch on the code and
 * display the detail verbatim.
 */

export class ApiError extends Error {
  constructor(code, detail, status) {
    super(detail);
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

/* The caps a body must respect, so the editor can refuse before it posts.
   Mirroring them client-side is a courtesy, not the defence: bounds.py is
   the defence, and it rejects rather than truncates. */
export async function getLimits() {
  return decode(await fetch("/limits"));
}

/* Clear, price and settle one scenario.
 *
 * config is the same declarative shape as configs/*.yaml. slack and limits
 * are clear()'s own arguments passed through: the editor always posts an
 * explicit slack and owns keeping it in step with its bus list (W2.6).
 */
export async function postClear({ config, slack = null, limits = null }, { signal } = {}) {
  return decode(
    await fetch("/clear", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ config, slack, limits }),
      signal,
    }),
  );
}
