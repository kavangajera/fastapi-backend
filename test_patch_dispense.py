"""
test_patch_dispense.py
──────────────────────
Test the PATCH /dispenses endpoint.

Simulates: user clicks edit on a dispense, changes one field (e.g. qty_disp),
and submits. Only that field should be updated; everything else stays the same.

Usage:
    uv run python test_patch_dispense.py
"""

import httpx
import json
import sys

BASE_URL = "http://localhost:5001"

# ─── Configuration ──────────────────────────────────────────────────
# Replace these with real values from your DB
MEDICAL_STORE_ID = 1
RX_NO_TO_PATCH = "12345"  # An rx_no that exists in the DB

# Auth token — paste a valid JWT here
AUTH_TOKEN = ""


def main():
    if not AUTH_TOKEN:
        print("⚠️  Set AUTH_TOKEN in the script before running!")
        print("   You can get one by logging in via the /auth/login endpoint.")
        sys.exit(1)

    headers = {
        "Authorization": f"Bearer {AUTH_TOKEN}",
        "Content-Type": "application/json",
    }

    # ─── Test 1: PATCH a single field on one rx_no ──────────────────
    print("=" * 60)
    print(f"Test 1: PATCH rx_no={RX_NO_TO_PATCH} — change only qty_disp")
    print("=" * 60)

    patch_body = {
        "medical_store_id": MEDICAL_STORE_ID,
        "dispenses": [
            {
                "rx_no": RX_NO_TO_PATCH,
                "qty_disp": "99",  # Only changing this field
                # All other fields are NOT sent — they stay untouched
            }
        ],
    }

    print(f"\nRequest body:\n{json.dumps(patch_body, indent=2)}")

    resp = httpx.patch(f"{BASE_URL}/dispenses", json=patch_body, headers=headers, timeout=30)
    print(f"\nStatus: {resp.status_code}")
    print(f"Response:\n{json.dumps(resp.json(), indent=2)}")

    # ─── Test 2: PATCH with a non-existent rx_no → expect 404 ──────
    print("\n" + "=" * 60)
    print("Test 2: PATCH with non-existent rx_no → expect 404")
    print("=" * 60)

    patch_body_404 = {
        "medical_store_id": MEDICAL_STORE_ID,
        "dispenses": [
            {
                "rx_no": "DOES_NOT_EXIST_99999",
                "qty_disp": "10",
            }
        ],
    }

    resp2 = httpx.patch(f"{BASE_URL}/dispenses", json=patch_body_404, headers=headers, timeout=30)
    print(f"\nStatus: {resp2.status_code}")
    print(f"Response:\n{json.dumps(resp2.json(), indent=2)}")

    # ─── Test 3: PATCH multiple fields on one rx_no ─────────────────
    print("\n" + "=" * 60)
    print(f"Test 3: PATCH rx_no={RX_NO_TO_PATCH} — change qty_disp + pat_name")
    print("=" * 60)

    patch_body_multi = {
        "medical_store_id": MEDICAL_STORE_ID,
        "dispenses": [
            {
                "rx_no": RX_NO_TO_PATCH,
                "qty_disp": "50",
                "pat_name": "John Doe (Edited)",
                # Everything else stays the same
            }
        ],
    }

    print(f"\nRequest body:\n{json.dumps(patch_body_multi, indent=2)}")
    resp3 = httpx.patch(f"{BASE_URL}/dispenses", json=patch_body_multi, headers=headers, timeout=30)
    print(f"\nStatus: {resp3.status_code}")
    print(f"Response:\n{json.dumps(resp3.json(), indent=2)}")


if __name__ == "__main__":
    main()
