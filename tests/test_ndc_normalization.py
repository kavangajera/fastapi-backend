"""NDC normalization: printed/hyphenated NDCs must fold to 11 digits.

Covers the pipeline choke points added for dashed-NDC documents:
  * `services.ndc_utils.to_ndc11`      — the rule table
  * `services.ndc_utils.ndc_for_storage` — the Medicine.ndc String(11) clamp
  * `CompactMedicine.ndc` validator    — extraction time (merge-key consistency)
  * `MedicineInput.ndc` validator      — save time (tier-1 sees normalized)

Every test here is a pure function call — no DB, no network, no LLM spend.
"""

import os

import pytest

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from schemas.save_dispense import DispenseSaveRequest, MedicineInput
from services.dispense_gemini_extractor import (
    CompactPage,
    _is_phantom_medicine,
    _merge_pages,
)
from services.ndc_utils import ndc_for_storage, to_ndc11
from services.validation import validate_tier1

# (raw printed value, expected normalized NDC11)
_RULE_TABLE = [
    ("12345678901", "12345678901"),  # already NDC11
    ("12345-6789-01", "12345678901"),  # 5-4-2 == NDC11 with separators
    ("0378-4275-77", "00378427577"),  # 4-4-2 -> pad labeler
    ("12345-678-90", "12345067890"),  # 5-3-2 -> pad product
    ("12345-6789-0", "12345678900"),  # 5-4-1 -> pad package
    ("0378 4275 77", "00378427577"),  # spaces are separators too
    ("0378.4275.77", "00378427577"),  # dots as well
    ("NDC 0378-4275-77", "00378427577"),  # label prefix tolerated
    ("  12345-6789-01  ", "12345678901"),  # surrounding whitespace
    ("0378427577", None),  # bare 10 -> ambiguous, never guessed
    ("12345-67890", None),  # 2 segments -> shape unknown
    ("123456789012", None),  # over-length
    ("1234", None),  # too short
    ("ABC", None),
    ("", None),
    (None, None),
]


@pytest.mark.parametrize("raw,expected", _RULE_TABLE)
def test_to_ndc11_rule_table(raw, expected) -> None:
    result = to_ndc11(raw)
    assert result == expected
    # The invariant every caller relies on: None, or exactly 11 digits.
    assert result is None or (len(result) == 11 and result.isdigit())


def test_bare_ten_digits_is_never_guessed() -> None:
    """A bare 10-digit NDC could pad three ways into three real products.

    Guessing would silently key inventory / reconciliation / the NDC cache
    with a plausible-but-wrong value, so it must stay unconverted.
    """
    assert to_ndc11("0378427577") is None


@pytest.mark.parametrize(
    "raw",
    [
        "0378-4275-771",
        "12345-6789-01",
        "garbage-value-here",
        "123456789012345",
        "NDC# 0378-4275-77 (bottle)",
        "",
        None,
    ],
)
def test_ndc_for_storage_always_fits_column(raw) -> None:
    """Medicine.ndc is String(11); an over-length value would be a 500."""
    stored = ndc_for_storage(raw)
    assert isinstance(stored, str)
    assert len(stored) <= 11


def test_ndc_for_storage_normalizes_when_it_can() -> None:
    assert ndc_for_storage("0378-4275-77") == "00378427577"
    assert ndc_for_storage("12345-6789-01") == "12345678901"


def test_ndc_for_storage_does_not_launder_garbage_into_valid_looking_ndc() -> None:
    """A clamped non-NDC must not come out matching ^\\d{11}$.

    Clamping the raw string (separators included) rather than the digits is
    what keeps the row visibly malformed after a force-save.
    """
    stored = ndc_for_storage("garbage-value-here")
    assert not (len(stored) == 11 and stored.isdigit())


# ── Extraction-time validator ────────────────────────────────────────────


def test_compact_medicine_normalizes_ndc() -> None:
    page = CompactPage.model_validate(
        {"p": 1, "m": [{"n": "DRUG A", "ndc": "0378-4275-77", "d": []}]}
    )
    assert page.medicines[0].ndc == "00378427577"


def test_compact_medicine_keeps_unnormalizable_ndc_verbatim() -> None:
    """Never drop the value — it is the only evidence tier-1 can flag."""
    page = CompactPage.model_validate({"p": 1, "m": [{"n": "X", "ndc": "12345", "d": []}]})
    assert page.medicines[0].ndc == "12345"


def test_merge_pages_collapses_dashed_and_plain_into_one_medicine() -> None:
    """Regression test for the duplicate-medicine bug.

    The same drug printed hyphenated on one page and bare on another used
    to produce two medicines with split dispenses and split totals, because
    `_merge_pages` keys on the raw NDC.
    """
    p1 = CompactPage.model_validate(
        {"p": 1, "m": [{"n": "DRUG A", "ndc": "0378-4275-77", "d": [{"rx": "1", "qd": "30"}]}]}
    )
    p2 = CompactPage.model_validate(
        {"p": 2, "m": [{"n": "DRUG A", "ndc": "00378427577", "d": [{"rx": "2", "qd": "60"}]}]}
    )

    merged = _merge_pages([p1.model_dump(exclude_none=True), p2.model_dump(exclude_none=True)])

    assert len(merged["medicines"]) == 1
    medicine = merged["medicines"][0]
    assert medicine["ndc"] == "00378427577"
    assert len(medicine["dispenses"]) == 2
    # Totals must reflect BOTH dispenses, not just the first page's.
    assert str(medicine["totals"]["total_quantity_dispensed"]) == "90"
    assert medicine["totals"]["total_rx_count"] == 2


# ── Save-time validator + tier-1 ─────────────────────────────────────────


def test_medicine_input_normalizes_ndc() -> None:
    medicine = MedicineInput.model_validate({"drug_name": "X", "ndc": "0378-4275-77"})
    assert medicine.ndc == "00378427577"


def test_medicine_input_keeps_unnormalizable_ndc_verbatim() -> None:
    medicine = MedicineInput.model_validate({"drug_name": "X", "ndc": "12345"})
    assert medicine.ndc == "12345"


def _save_request(ndc: str) -> DispenseSaveRequest:
    return DispenseSaveRequest.model_validate(
        {
            "medical_store_id": 1,
            "medicines": [
                {
                    "drug_name": "DRUG A",
                    "ndc": ndc,
                    "dispenses": [
                        {"rx_no": "1", "date_filled": "01/01/2026", "qty_disp": "30", "days_supply": "30"}
                    ],
                }
            ],
        }
    )


def _malformed_ndc_alerts(report) -> list:
    return [a for a in report.alerts if a.code == "MALFORMED_NDC"]


def test_tier1_accepts_hyphenated_ndc_after_normalization() -> None:
    """The 422 this whole change exists to remove.

    A legitimately hyphenated NDC used to raise MALFORMED_NDC and block the
    save; the schema validator now normalizes before tier-1 ever sees it.
    """
    report = validate_tier1(_save_request("0378-4275-77").model_dump(mode="json"))
    assert _malformed_ndc_alerts(report) == []


def test_tier1_still_rejects_genuinely_malformed_ndc() -> None:
    """Normalization must not paper over real problems."""
    report = validate_tier1(_save_request("12345").model_dump(mode="json"))
    assert _malformed_ndc_alerts(report)


# ── Phantom insurance/BIN rows ───────────────────────────────────────────
#
# Wide daily-log layouts print an `Ins\Bin` column beside the drug column;
# the model sometimes reads a carrier code + 6-digit BIN as a drug + NDC.


@pytest.mark.parametrize(
    "medicine,is_phantom",
    [
        # carrier name + BIN in the ndc slot, no dispenses -> phantom
        ({"drug_name": "CIGNA", "ndc": "610606", "dispenses": [], "totals": {"packs": "35"}}, True),
        # same row after the prompt stopped putting the BIN in ndc
        ({"drug_name": "AC1", "ndc": None, "dispenses": [], "totals": {}}, True),
        # a real summary-only row: no dispenses, but a resolvable NDC -> keep
        (
            {
                "drug_name": "ATORVASTATIN 10MG",
                "ndc": "70377007713",
                "dispenses": [],
                "totals": {"packs": "0.09"},
            },
            False,
        ),
        # hyphenated NDC still resolves, so still not a phantom
        ({"drug_name": "DRUG", "ndc": "0378-4275-77", "dispenses": [], "totals": {}}, False),
        # daily-log format prints no NDC at all, but the row has dispenses -> keep
        ({"drug_name": "DRUG", "ndc": None, "dispenses": [{"rx_no": "1"}], "totals": {}}, False),
    ],
)
def test_is_phantom_medicine(medicine, is_phantom) -> None:
    assert _is_phantom_medicine(medicine) is is_phantom


def test_merge_pages_drops_insurance_rows_but_keeps_real_medicines() -> None:
    page = CompactPage.model_validate(
        {
            "p": 1,
            "m": [
                {"n": "OLMESA/AMLOD/HCTZ", "ndc": "13668-0382-30", "d": [{"rx": "1", "qd": "30"}]},
                # BIN misread as a drug row
                {"n": "CIGNA", "ndc": "610606", "d": []},
                # and the ndc-less variant of the same mistake
                {"n": "AC1", "d": []},
            ],
        }
    )

    merged = _merge_pages([page.model_dump(exclude_none=True)])

    assert len(merged["medicines"]) == 1
    assert merged["medicines"][0]["ndc"] == "13668038230"
    assert len(merged["medicines"][0]["dispenses"]) == 1


def test_merge_pages_keeps_summary_only_medicine() -> None:
    """A per-drug totals block has no dispenses and must not be mistaken
    for an insurance row."""
    page = CompactPage.model_validate(
        {"p": 1, "m": [{"n": "ATORVASTATIN 10MG", "ndc": "70377-0077-13", "t": {"pk": "0.09"}}]}
    )

    merged = _merge_pages([page.model_dump(exclude_none=True)])

    assert len(merged["medicines"]) == 1
    assert merged["medicines"][0]["ndc"] == "70377007713"


# ── Payload must survive the Kafka publish path ──────────────────────────
#
# The worker json.dumps() the extraction result twice: once for the DB
# (with default=str) and once for Kafka (`kafka_infra/producer.py`). A
# Decimal in `totals` passed the first and crashed the second in
# production, so assert the payload is JSON-native on its own.


def test_merge_pages_output_is_json_serializable_without_default() -> None:
    import json

    page = CompactPage.model_validate(
        {
            "p": 1,
            "m": [
                {
                    "n": "DRUG A",
                    "ndc": "0378-4275-77",
                    "d": [{"rx": "1", "qd": "30.5", "pr": "$4.80"}, {"rx": "2", "qd": "60"}],
                }
            ],
        }
    )
    merged = _merge_pages([page.model_dump(exclude_none=True)])

    # No default= fallback: this is exactly what the Kafka producer does.
    json.dumps(merged)

    totals = merged["medicines"][0]["totals"]
    assert totals["total_quantity_dispensed"] == "90.5"
    assert totals["total_rx_count"] == 2  # int keeps its type
