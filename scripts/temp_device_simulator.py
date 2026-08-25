"""
scripts/temp_device_simulator.py
────────────────────────────────
Pretend to be a temperature logger, so the whole flow can be exercised without
hardware. It speaks the same endpoints real firmware does, and nothing else —
no user token is ever involved.

    # register a device first (from the dashboard, or Swagger), then:
    python -m scripts.temp_device_simulator --secret tdev_xxx

    # options
    --url        API base URL          (default http://localhost:5001)
    --interval   seconds between pushes (default 5)
    --batch      readings per push      (default 3)
    --count      number of pushes, 0 = forever (default 0)
    --min/--max  temperature range      (default 2.0 / 8.0)
    --drift      chance of an out-of-range excursion, 0-1 (default 0.1)
    --no-stop    leave the session open on exit instead of stopping it

What it demonstrates, in order:

    1. POST /temperature-devices/logging/start   secret        → session + token
    2. POST /temperature-logs                    token + array → readings stored
    3. POST /temperature-devices/logging/token   secret        → token renewed
       (automatic, on the 401 that says TOKEN_EXPIRED)
    4. POST /temperature-devices/logging/stop    secret        → token invalidated

Ctrl-C stops logging cleanly, which is the point of step 4: the token the
simulator was holding stops working the instant the session closes.
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timezone

import httpx


def _log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def _unwrap(response: httpx.Response) -> dict:
    """Every endpoint answers with the {status_code, message, data} envelope."""
    body = response.json()
    if response.is_error:
        raise RuntimeError(body.get("message") or response.text)
    return body.get("data") or {}


class SimulatedDevice:
    def __init__(self, base_url: str, secret: str) -> None:
        self.client = httpx.Client(base_url=base_url.rstrip("/"), timeout=30.0)
        self.secret = secret
        self.token: str | None = None
        self.session_id: int | None = None

    # ── lifecycle ───────────────────────────────────────────────────
    def start(self) -> None:
        data = _unwrap(
            self.client.post(
                "/temperature-devices/logging/start", json={"device_secret": self.secret}
            )
        )
        self.token = data["access_token"]
        self.session_id = data["session_id"]
        _log(
            f"{'Resumed' if data.get('resumed') else 'Started'} session {self.session_id} "
            f"on '{data['nickname']}' (pharmacy {data['pharmacy_id']}); "
            f"token valid until {data['expires_at']}"
        )

    def renew(self) -> None:
        data = _unwrap(
            self.client.post(
                "/temperature-devices/logging/token", json={"device_secret": self.secret}
            )
        )
        self.token = data["access_token"]
        _log(f"Token renewed for session {data['session_id']} — same run continues")

    def stop(self) -> None:
        data = _unwrap(
            self.client.post(
                "/temperature-devices/logging/stop", json={"device_secret": self.secret}
            )
        )
        if data.get("already_stopped"):
            _log("Nothing was running.")
        else:
            session = data.get("session") or {}
            _log(
                f"Stopped session {session.get('session_id')} after "
                f"{session.get('readings_count', 0)} readings — token is now invalid"
            )

    # ── pushing ─────────────────────────────────────────────────────
    def push(self, readings: list[dict]) -> dict:
        """Send one batch, transparently re-authenticating on an expired token."""
        response = self.client.post(
            "/temperature-logs",
            json=readings,
            headers={"Authorization": f"Bearer {self.token}"},
        )
        if response.status_code == 401:
            reason = (response.json().get("data") or {}).get("reason")
            if reason in ("TOKEN_EXPIRED", "TOKEN_REVOKED"):
                # Step 4 of the flow: the secret buys a new token, same session.
                _log(f"Token rejected ({reason}); re-authenticating with the secret…")
                self.renew()
                response = self.client.post(
                    "/temperature-logs",
                    json=readings,
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            elif reason == "SESSION_STOPPED":
                raise RuntimeError("Logging was stopped for this device (from the dashboard?).")
        return _unwrap(response)

    def close(self) -> None:
        self.client.close()


def make_readings(count: int, lo: float, hi: float, drift: float) -> list[dict]:
    """A batch shaped the way firmware sends it: [{time, temp, probe}, …]."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    out = []
    for _ in range(count):
        if random.random() < drift:
            # An excursion, so the dashboard's High/Low banding has something
            # to show.
            temp = random.choice([round(lo - random.uniform(0.5, 3), 1),
                                  round(hi + random.uniform(0.5, 3), 1)])
        else:
            temp = round(random.uniform(lo, hi), 1)
        out.append({
            "time": now.isoformat(timespec="seconds"),
            "temp": temp,
            "probe": "PRB-001",
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Simulate a temperature logging device.")
    p.add_argument("--secret", required=True, help="The device secret from registration.")
    p.add_argument("--url", default="http://localhost:5001", help="API base URL.")
    p.add_argument("--interval", type=float, default=5.0, help="Seconds between pushes.")
    p.add_argument("--batch", type=int, default=3, help="Readings per push.")
    p.add_argument("--count", type=int, default=0, help="Number of pushes; 0 = forever.")
    p.add_argument("--min", dest="lo", type=float, default=2.0, help="Low end of normal range.")
    p.add_argument("--max", dest="hi", type=float, default=8.0, help="High end of normal range.")
    p.add_argument("--drift", type=float, default=0.1, help="Excursion probability, 0-1.")
    p.add_argument("--no-stop", action="store_true", help="Leave the session open on exit.")
    args = p.parse_args()

    device = SimulatedDevice(args.url, args.secret)
    pushes = 0
    try:
        device.start()
        while args.count == 0 or pushes < args.count:
            batch = make_readings(args.batch, args.lo, args.hi, args.drift)
            result = device.push(batch)
            pushes += 1
            temps = ", ".join(f"{r['temp']}°C" for r in batch)
            _log(f"Pushed {result['stored']} [{temps}] — session total {result['session_readings_count']}")
            if args.count and pushes >= args.count:
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
        _log("Interrupted.")
    except RuntimeError as exc:
        _log(f"ERROR: {exc}")
        return 1
    finally:
        if not args.no_stop:
            try:
                device.stop()
            except RuntimeError as exc:
                _log(f"Could not stop cleanly: {exc}")
        else:
            _log("Leaving the session open (--no-stop).")
        device.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
