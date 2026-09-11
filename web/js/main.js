/* W2.0 smoke: prove the page is served, the module graph loads, and the
 * server answers. Everything visible here is replaced by the editor in W2.1
 * onward -- this file exists so a failure at W2.1 is a failure in the editor
 * and not in the plumbing underneath it.
 */

import { ApiError, getLimits } from "./api.js";

const status = document.querySelector("#status");
const limits = document.querySelector("#limits");

function row(term, value) {
  const dt = document.createElement("dt");
  dt.textContent = term;
  const dd = document.createElement("dd");
  dd.textContent = value;
  limits.append(dt, dd);
}

try {
  const caps = await getLimits();
  row("Buses", caps.max_buses);
  row("Branches", caps.max_branches);
  row("Generators", caps.max_generators);
  row("Hours", caps.max_hours);
  row("Body (bytes)", caps.max_body_bytes.toLocaleString());
  row("Load sources", caps.load_sources.join(", "));
  status.textContent = "Server reachable.";
} catch (err) {
  status.dataset.state = "error";
  status.textContent =
    err instanceof ApiError ? `${err.code}: ${err.detail}` : String(err);
}
