"""Item 2 — NDC_NOT_FOUND alert uses plain, non-jargon language.

Pure function test: `_module_a` just needs a cache_row (or None) and an
alerts list — no DB, no network.
"""

from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from schemas.validation import Alert
from services.validation.tier2 import _module_a


def test_ndc_not_found_suggestion_is_plain_language() -> None:
    alerts: list[Alert] = []
    _module_a(
        mi=0,
        ndc11="00000000000",
        med={"drug_name": "MYSTERY DRUG"},
        cache_row=None,
        today=date(2026, 1, 1),
        alerts=alerts,
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.code == "NDC_NOT_FOUND"
    assert alert.severity == "WARNING"

    # The old jargon ("Verify NDC manually; devices live in the FDA Device
    # DB, not Drug.") must be gone.
    assert "Device DB" not in alert.suggestion
    assert "Verify NDC manually" not in alert.suggestion

    # Plain-language replacement, still conveying the same meaning.
    assert "device" in alert.suggestion.lower()
    assert "not an error" in alert.suggestion.lower()


def test_ndc_not_found_message_mentions_discontinued_as_a_cause() -> None:
    """Confirmed live against a real discontinued NDC earlier in this
    session (Ozempic 2mg) — NOT_FOUND can genuinely mean delisted, not
    just device/recent-launch, so the message should say so."""
    alerts: list[Alert] = []
    _module_a(
        mi=0,
        ndc11="00000000000",
        med={"drug_name": "X"},
        cache_row=None,
        today=date(2026, 1, 1),
        alerts=alerts,
    )
    assert "discontinued" in alerts[0].message.lower()
