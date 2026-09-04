"""Item 8 — per-patient totals no longer blend dispenses under differing
insurance for the same patient into one row (Module G / `_grand_total_recompute`).

Pure function tests via `validate_tier1` — no DB, no network.
"""

from __future__ import annotations

import os

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from services.validation.tier1 import validate_tier1

_SAME_PATIENT = dict(pat_name="DOE, JOHN", pat_phone="5551234567", pat_addr="1 Main St, 10001")


def _report_data(dispenses: list[dict]) -> dict:
    return {"medicines": [{"ndc": "11111111111", "drug_name": "DRUG A", "dispenses": dispenses}]}


def test_same_patient_different_insurance_produces_two_rows() -> None:
    dispenses = [
        {**_SAME_PATIENT, "rx_no": "1", "price": "100", "ins_paid": "80", "ins_code": "AETNA"},
        {**_SAME_PATIENT, "rx_no": "2", "price": "50", "ins_paid": "40", "ins_code": "CASH"},
    ]
    report = validate_tier1(_report_data(dispenses), granted=None)

    assert len(report.per_patient) == 2
    insurances = {row.insurance for row in report.per_patient}
    assert insurances == {"AETNA", "CASH"}
    for row in report.per_patient:
        assert row.rx_count == 1  # never blended across insurance


def test_same_patient_same_insurance_still_sums_together() -> None:
    """Multiple Rx's for the same patient UNDER THE SAME insurance is a
    legitimate single total — only differing insurance must not merge."""
    dispenses = [
        {**_SAME_PATIENT, "rx_no": "1", "price": "100", "ins_paid": "80", "ins_code": "AETNA"},
        {**_SAME_PATIENT, "rx_no": "2", "price": "50", "ins_paid": "40", "ins_code": "AETNA"},
    ]
    report = validate_tier1(_report_data(dispenses), granted=None)

    assert len(report.per_patient) == 1
    row = report.per_patient[0]
    assert row.rx_count == 2
    assert row.total_price == "150"
    assert row.total_ins_paid == "120"


def test_grand_total_still_sums_everything_regardless_of_insurance() -> None:
    """The report-wide grand_total is intentionally unaffected by this
    change — only per-patient totals stop merging."""
    dispenses = [
        {**_SAME_PATIENT, "rx_no": "1", "price": "100", "ins_paid": "80", "ins_code": "AETNA"},
        {**_SAME_PATIENT, "rx_no": "2", "price": "50", "ins_paid": "40", "ins_code": "CASH"},
    ]
    report = validate_tier1(_report_data(dispenses), granted=None)

    assert report.grand_total.recomputed_sum_price == "150"
    assert report.grand_total.recomputed_sum_ins_paid == "120"
    assert report.grand_total.recomputed_rx_count == 2


def test_different_patients_never_merge_regardless_of_insurance() -> None:
    dispenses = [
        {**_SAME_PATIENT, "rx_no": "1", "price": "100", "ins_paid": "80", "ins_code": "AETNA"},
        {
            "pat_name": "SMITH, JANE",
            "pat_phone": "5559876543",
            "pat_addr": "2 Elm St, 20002",
            "rx_no": "2",
            "price": "50",
            "ins_paid": "40",
            "ins_code": "AETNA",
        },
    ]
    report = validate_tier1(_report_data(dispenses), granted=None)
    assert len(report.per_patient) == 2
