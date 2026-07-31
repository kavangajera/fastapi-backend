import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

os.environ.setdefault("FRONTEND_URL", "http://localhost")
os.environ.setdefault("DATABASE_URL", "mysql+asyncmy://root:root@localhost/test")
os.environ.setdefault("SECRET_KEY", "test-only-secret")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "30")
os.environ.setdefault("REFRESH_TOKEN_EXPIRE_DAYS", "7")

from kafka_worker.errors import PermanentDocumentError
from kafka_worker.handlers.dispense_handler import handle_dispense
from services.dispense_gemini_extractor import CompactPage, _merge_pages, extraction_tool
from services.invoice_extractor import TOOL_NAME as INVOICE_TOOL_NAME
from services.invoice_extractor import _tool as invoice_tool
from services.legacy_layout import validated_legacy_extract
from services.legacy_pdf_extractor import extract_report as extract_legacy_pdf

SAMPLE_DIR = Path(r"C:\Users\baps\Downloads\demo_app\docs")


def _legacy_report() -> dict:
    return {
        "pharmacy": {},
        "grand_total": {"total_rx_count": "1"},
        "medicines": [
            {
                "drug_name": "DRUG A",
                "ndc": "12345678901",
                "totals": {},
                "dispenses": [{"rx_no": "1", "date_filled": "01/01/2026"}],
            }
        ],
    }


def test_legacy_quality_gate_accepts_complete_detail_report() -> None:
    assert validated_legacy_extract(lambda _: _legacy_report(), b"data") is not None


def test_legacy_quality_gate_rejects_summary_only_report() -> None:
    report = _legacy_report()
    report["medicines"][0]["dispenses"] = []
    assert validated_legacy_extract(lambda _: report, b"data") is None


def test_tool_schema_and_page_model_forbid_unknown_fields() -> None:
    assert extraction_tool()["function"]["name"] == "extract_dispense_page"
    with pytest.raises(ValueError):
        CompactPage.model_validate({"p": 1, "unknown": "value"})


def test_invoice_uses_forced_tool_contract() -> None:
    assert invoice_tool()["function"]["name"] == INVOICE_TOOL_NAME


def test_merge_preserves_page_order_and_source_page() -> None:
    pages = [
        {
            "source_page": 1,
            "pharmacy": {"pharmacy_name": "Test"},
            "grand_total": {},
            "medicines": [
                {
                    "drug_name": "A",
                    "ndc": "12345678901",
                    "dispenses": [{"rx_no": "1"}],
                }
            ],
        },
        {
            "source_page": 2,
            "pharmacy": {},
            "grand_total": {"total_rx_count": "2"},
            "medicines": [
                {
                    "drug_name": "A",
                    "ndc": "12345678901",
                    "dispenses": [{"rx_no": "2"}],
                }
            ],
        },
    ]
    result = _merge_pages(pages)
    rows = result["medicines"][0]["dispenses"]
    assert [row["rx_no"] for row in rows] == ["1", "2"]
    assert [row["source_page"] for row in rows] == [1, 2]


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="local integration samples unavailable")
def test_sample_pdf_selects_legacy_and_has_expected_counts() -> None:
    sample = (SAMPLE_DIR / "sample 01 doc-copy.pdf").read_bytes()
    report = validated_legacy_extract(extract_legacy_pdf, sample)
    assert report is not None
    assert len(report["medicines"]) == 85
    assert sum(len(medicine["dispenses"]) for medicine in report["medicines"]) == 99
    assert report["grand_total"]["total_rx_count"] == "99"


@pytest.mark.skipif(not SAMPLE_DIR.exists(), reason="local integration samples unavailable")
def test_first_sample_page_marks_trailing_partial_row() -> None:
    source = fitz.open(SAMPLE_DIR / "sample 01 doc-copy.pdf")
    page = fitz.open()
    page.insert_pdf(source, from_page=0, to_page=0)
    report = validated_legacy_extract(extract_legacy_pdf, page.tobytes())
    assert report is not None
    rows = [row for medicine in report["medicines"] for row in medicine["dispenses"]]
    assert rows[-1]["rx_no"] == "509573"
    assert rows[-1]["is_partial"] is True


def test_patch_document_without_rx_is_non_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "kafka_worker.handlers.dispense_handler.document_storage.retrieve",
        lambda _: b"document",
    )
    monkeypatch.setattr(
        "kafka_worker.handlers.dispense_handler.extract_report_from_file",
        lambda *_: {"pharmacy": {}, "grand_total": {}, "medicines": []},
    )
    document = SimpleNamespace(
        storage_path="ignored",
        original_filename="report.pdf",
        doc_key="key",
        id=1,
        progress={"request_mode": "patch"},
    )
    with pytest.raises(PermanentDocumentError) as error:
        asyncio.run(handle_dispense(SimpleNamespace(), document, medical_store_id=1))
    assert error.value.status_code == 400
