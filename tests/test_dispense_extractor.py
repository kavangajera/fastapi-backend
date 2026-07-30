import pytest
from unittest.mock import patch, MagicMock
from services.dispense_llm_extractor import process_text_doc, merge_chunks

def test_merge_chunks_empty():
    assert merge_chunks([]) == {"pharmacy": {}, "medicines": [], "grand_total": {}}

def test_merge_chunks_pharmacy_and_grand_total():
    chunk1 = {
        "pharmacy": {"pharmacy_name": "Test Pharm", "address": "123 Main"},
        "medicines": [],
        "grand_total": {"total_price": "100.00"}
    }
    chunk2 = {
        "pharmacy": {"pharmacy_name": "Should Not Overwrite"},
        "medicines": [],
        "grand_total": {"total_price": "200.00", "total_rx_count": "5"}
    }
    result = merge_chunks([chunk1, chunk2])
    assert result["pharmacy"]["pharmacy_name"] == "Test Pharm"
    assert result["pharmacy"]["address"] == "123 Main"
    assert result["grand_total"]["total_price"] == "200.00"  # Last wins for GT
    assert result["grand_total"]["total_rx_count"] == "5"

def test_merge_chunks_medicines():
    chunk1 = {
        "pharmacy": {},
        "medicines": [
            {
                "drug_name": "DRUG A",
                "ndc": "12345678901",
                "dispenses": [{"rx_no": "1"}],
                "totals": {"packs": "10"}
            }
        ],
        "grand_total": {}
    }
    chunk2 = {
        "pharmacy": {},
        "medicines": [
            {
                "drug_name": "DRUG A",
                "ndc": "12345678901",
                "dispenses": [{"rx_no": "2"}],
                "totals": {"total_price": "50.00"}
            },
            {
                "drug_name": "DRUG B",
                "ndc": "98765432109",
                "dispenses": [{"rx_no": "3"}],
                "totals": {}
            }
        ],
        "grand_total": {}
    }
    result = merge_chunks([chunk1, chunk2])
    assert len(result["medicines"]) == 2
    drug_a = next(m for m in result["medicines"] if m["ndc"] == "12345678901")
    drug_b = next(m for m in result["medicines"] if m["ndc"] == "98765432109")
    
    assert len(drug_a["dispenses"]) == 2
    assert drug_a["dispenses"][0]["rx_no"] == "1"
    assert drug_a["dispenses"][1]["rx_no"] == "2"
    assert drug_a["totals"]["packs"] == "10"
    assert drug_a["totals"]["total_price"] == "50.00"
    
    assert len(drug_b["dispenses"]) == 1
    assert drug_b["dispenses"][0]["rx_no"] == "3"

@patch("services.dispense_llm_extractor.call_llm")
def test_process_text_doc_chunking(mock_call_llm):
    mock_call_llm.return_value = {
        "pharmacy": {"pharmacy_name": "Mock Pharm"},
        "medicines": [],
        "grand_total": {}
    }
    
    lines = ["Line"] * 250
    result = process_text_doc(lines)
    
    assert mock_call_llm.call_count == 3  # 250 lines / 100 chunk size = 3 chunks
    assert result["pharmacy"]["pharmacy_name"] == "Mock Pharm"
