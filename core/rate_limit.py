"""
core/rate_limit.py
──────────────────
A small in-process sliding-window limiter for the unauthenticated auth
endpoints, keyed on **the email address being acted upon** — never on the
caller's IP.

Why not per-IP: a pharmacy counter, an office, a shared WiFi network or a
mobile carrier behind CGNAT all present one address for many people. An
IP budget makes those users throttle each other — one owner registering
their second pharmacy would lock out the colleague signing up beside
them. Keying on the email means a caller's budget follows the account
they are actually trying to create, so no two applicants can collide.

What this buys, and what it does not: it bounds how often a *single*
address can be probed or mailed, which caps how much mail one mailbox can
be made to receive and stops the 409 "already registered" answer being
re-asked in a loop for the same address. It does **not** bound a caller
who walks a list of many addresses — every new address starts with a full
budget. Enumeration across addresses has to be stopped at the edge
(nginx / Cloudflare / API gateway), which is where connection-level and
per-source limits belong anyway.

Scope, stated plainly: the window lives in **this process's memory**. With
N API instances behind a load balancer the effective allowance is N × the
limit, and a restart clears it. That is a deliberate trade — it costs
nothing and needs no Redis. Note that the durable half of the protection
does not have this weakness: the cooldown and total-send caps in
`services/signup_service.py` live on the `pending_signup` row, so they
hold across instances and restarts regardless.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException

# key → timestamps (monotonic seconds) of the hits still inside the window.
_BUCKETS: dict[str, deque[float]] = {}

# Housekeeping: drop emptied buckets once the table grows past this, so a
# long-lived process does not accumulate one entry per address ever seen.
_SWEEP_THRESHOLD = 4096


def _sweep(now: float, window_seconds: int) -> None:
    for key in [k for k, hits in _BUCKETS.items() if not hits or now - hits[-1] > window_seconds]:
        _BUCKETS.pop(key, None)


def subject_key(subject: str, scope: str) -> str:
    """Limiter key for one subject (an email address), namespaced by `scope`.

    Case- and whitespace-folded so `Foo@x.com ` and `foo@x.com` share a
    bucket. Callers pass an already-normalized address; this is belt and
    braces so a missed validator cannot hand out a second free budget.
    """
    return f"{scope}:{subject.strip().lower()}"


def enforce(
    key: str,
    *,
    limit: int,
    window_seconds: int,
    message: str = "Too many requests. Please try again later.",
) -> None:
    """Record a hit against `key`; raise 429 once `limit` is exceeded.

    Sync and free of `await`, so it runs to completion without another
    coroutine interleaving — no locking needed on the event loop.
    """
    if limit <= 0:
        return

    now = time.monotonic()
    hits = _BUCKETS.setdefault(key, deque())

    cutoff = now - window_seconds
    while hits and hits[0] <= cutoff:
        hits.popleft()

    if len(hits) >= limit:
        retry_after = max(1, int(window_seconds - (now - hits[0])))
        raise HTTPException(
            status_code=429,
            detail={
                "status_code": 429,
                "message": f"{message} (retry in {retry_after}s)",
                "data": None,
            },
            headers={"Retry-After": str(retry_after)},
        )

    hits.append(now)

    if len(_BUCKETS) > _SWEEP_THRESHOLD:
        _sweep(now, window_seconds)


def reset(key: str | None = None) -> None:
    """Clear one key, or everything. Test/ops helper — not used by the app."""
    if key is None:
        _BUCKETS.clear()
    else:
        _BUCKETS.pop(key, None)
