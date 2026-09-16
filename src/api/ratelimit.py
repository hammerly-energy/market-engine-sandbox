"""Per-IP rate limiting for the one endpoint that costs something.

`_read_capped` in app.py bounds a single request and says so in its own
docstring: many at once is a reverse proxy's job. On a deploy there is no
reverse proxy of this repo's own, and every POST /clear starts an LP solve, so
the gap that docstring names is the gap a public URL actually falls into. This
module closes it at the smallest size that works.

Three things it is not, so nobody builds on it as though it were:

  - **In-process.** The counter lives in this worker. It resets on restart and
    two replicas each allow the full rate, so the deploy runs one.
  - **Trusting.** It keys on the address a proxy reports in X-Forwarded-For,
    which a caller ahead of a trusted proxy can set to anything. A real
    defence authenticates or sits at the edge.
  - **Not a queue.** A request over the limit is refused, not delayed. A
    visitor who hits it gets a sentence and their next solve a moment later.

The numbers are generous against a person and tight against a loop. Dragging a
slider is the heaviest honest use of this page and it coalesces (W2.2), so a
visitor sends a solve per gesture rather than per pixel.
"""

import os
import time
from collections import OrderedDict, deque

from src.api.bounds import BadRequest

WINDOW_S = 60.0

# Overridable so a deploy can tighten it without an edit. Read once at import:
# a limit that changed under a running process would make two identical
# requests a minute apart get different answers for no reason a caller sees.
MAX_SOLVES = int(os.environ.get("MARKET_ENGINE_MAX_SOLVES_PER_MIN", "30"))

# Bounded memory. Each tracked address costs a deque of at most MAX_SOLVES
# floats, so the table cannot grow without limit under a spray of forged
# X-Forwarded-For values -- which is the one attack the header's spoofability
# actually hands over.
MAX_TRACKED = 4096


class RateLimiter:
    """A sliding window of hit times per address.

    Sliding rather than a fixed window because a fixed one lets a caller send
    the full allowance in the last second of one window and again in the first
    second of the next, which is twice the rate the number claims.
    """

    def __init__(self, max_calls=MAX_SOLVES, window_s=WINDOW_S, max_tracked=MAX_TRACKED):
        self.max_calls = max_calls
        self.window_s = window_s
        self.max_tracked = max_tracked
        self._hits = OrderedDict()

    def check(self, key, now=None):
        """Record one call, or raise BadRequest with status 429."""
        now = time.monotonic() if now is None else now

        hits = self._hits.get(key)
        if hits is None:
            hits = deque()
            self._hits[key] = hits
        self._hits.move_to_end(key)

        cutoff = now - self.window_s
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.max_calls:
            retry = max(1, int(self.window_s - (now - hits[0])) + 1)
            raise BadRequest(
                "rate_limited",
                f"{self.max_calls} solves a minute per address is the limit; "
                f"try again in {retry}s",
                429,
            )

        hits.append(now)

        # Evict least-recently-seen first. An address whose window has emptied
        # is indistinguishable from one never seen, so dropping it loses
        # nothing -- it simply starts counting again.
        while len(self._hits) > self.max_tracked:
            self._hits.popitem(last=False)


def client_ip(request):
    """The caller's address as well as this process can know it.

    Behind a proxy `request.client.host` is the proxy, so every visitor would
    share one bucket and the first busy one would lock out the rest. The first
    hop of X-Forwarded-For is the client the edge saw. It is a claim, not a
    fact -- see the module docstring.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


limiter = RateLimiter()
