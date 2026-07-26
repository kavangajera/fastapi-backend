"""
core/rate_limit.py
──────────────────
A small in-process sliding-window limiter for the unauthenticated auth
endpoints.

Why it exists: signup answers "is this email already registered?" with a
409, which is friendlier than a generic response but also makes the
endpoint an oracle. Capping how many times one caller may ask — and how
much mail one address can be made to generate — is what keeps that answer
from being harvestable in bulk.

Scope, stated plainly: the window lives in **this process's memory**. With
N API instances behind a load balancer the effective allowance is N × the
limit, and a restart clears it. That is a deliberate trade — it costs
nothing and needs no Redis — and it is enough to stop a single client
hammering the endpoint. It is not a defence against a distributed
attacker; put a real limiter at the edge (nginx / Cloudflare / API
gateway) if you need that.

`X-Forwarded-For` is deliberately **not** consulted: the header is
attacker-controlled unless a trusted proxy rewrites it, and honouring it
blindly would make the limiter bypassable by anyone who can set a header.
If this app is ever fronted by a proxy you control, run uvicorn with
`--proxy-headers --forwarded-allow-ips=<proxy ip>` — Starlette then
rewrites `request.client` itself and this module needs no change.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import HTTPException, Request

# key → timestamps (monotonic seconds) of the hits still inside the window.
_BUCKETS: dict[str, deque[float]] = {}

# Housekeeping: drop emptied buckets once the table grows past this, so a
# long-lived process does not accumulate one entry per IP ever seen.
_SWEEP_THRESHOLD = 4096


def _sweep(now: float, window_seconds: int) -> None:
    for key in [k for k, hits in _BUCKETS.items() if not hits or now - hits[-1] > window_seconds]:
        _BUCKETS.pop(key, None)


def client_key(request: Request, scope: str) -> str:
    """Limiter key for a request: the peer IP, namespaced by `scope`."""
    host = request.client.host if request.client else "unknown"
    return f"{scope}:{host}"


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
