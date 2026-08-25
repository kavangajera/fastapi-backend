"""End-to-end smoke test against the Dockerised MySQL + running API."""
import json
import sys

import httpx

BASE = "http://127.0.0.1:5099"
OWNER = sys.argv[1]
TECH = sys.argv[2]
PH = int(sys.argv[3])
H = {"Authorization": "Bearer " + OWNER}
HT = {"Authorization": "Bearer " + TECH}
c = httpx.Client(base_url=BASE, timeout=60.0)

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    mark = "PASS" if cond else "FAIL"
    line = "  [" + mark + "] " + name
    if detail and not cond:
        line += "  -- " + str(detail)
    print(line)


def data(r):
    try:
        j = r.json()
        return j.get("data", j)
    except Exception:
        return r.text


NDC_A = "00002322730"   # stocked via invoice
NDC_B = "11111111111"   # never purchased -> Module I should fire


def inv_map():
    r = c.get("/pharmacy/" + str(PH) + "/inventory?limit=500", headers=H)
    return {i["code"]: i for i in data(r)["items"]}


def qty(m, ndc):
    return m.get(ndc, {}).get("quantity")


print("")
print("== A. INVOICE -> INVENTORY (+ received_date) ==")
invoice_body = {
    "medical_store_id": PH, "seller_name": "ACME Wholesale",
    "invoice_number": "INV-1001", "invoice_date": "03/04/2026",
    "line_items": [
        {"ndc11": NDC_A, "description": "TESTDRUG 500MG", "invoiced_qty": "100",
         "unit_price": "1.50", "lot_number": "L1"},
    ],
    "summary": {"grand_total": "150.00"},
}
r = c.post("/invoices", json=invoice_body, headers=H)
check("POST /invoices succeeds", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:300])
inv_id = data(r).get("invoice_id")

m = inv_map()
check("inventory +100 from invoice", qty(m, NDC_A) == "100.000", "got " + str(qty(m, NDC_A)))
check("received_date parsed from invoice_date (US month-first)",
      m.get(NDC_A, {}).get("received_date") == "2026-03-04",
      "got " + str(m.get(NDC_A, {}).get("received_date")))

r = c.get("/pharmacy/" + str(PH) + "/inventory?received_from=2026-03-01&received_to=2026-03-31", headers=H)
check("date filter includes in-range stock", len(data(r)["items"]) == 1, str(data(r)["total"]))
r = c.get("/pharmacy/" + str(PH) + "/inventory?received_from=2026-04-01", headers=H)
check("date filter excludes out-of-range stock", len(data(r)["items"]) == 0, str(data(r)["total"]))
r = c.get("/pharmacy/" + str(PH) + "/inventory", headers=H)
check("no filter = current inventory (all rows)", len(data(r)["items"]) == 1)


def dispense_body(ndc, rx, q="10", force=False):
    return {
        "medical_store_id": PH, "force_save": force,
        "pharmacy": {"report_from_date": "2026-03-01", "report_to_date": "2026-03-31"},
        "grand_total": {"total_rx_count": 1, "total_price": "20.00"},
        "medicines": [{
            "drug_name": "TESTDRUG", "ndc": ndc,
            "dispenses": [{"qty_disp": q, "rx_no": rx, "date_filled": "03/15/2026",
                           "days_supply": "30", "pat_name": "DOE, JOHN",
                           "price": "20.00", "ins_paid": "20.00", "ins_code": "01"}],
        }],
    }


print("")
print("== B. MODULE I (stock on hand) ==")
r = c.post("/dispenses/validate", json=dispense_body(NDC_B, "RX-B1"), headers=H)
alerts = [a for a in data(r).get("alerts", []) if a.get("code") == "NO_INVENTORY_FOR_DISPENSE"]
check("Module I fires for never-purchased NDC", len(alerts) == 1, json.dumps(data(r))[:300])
check("Module I severity is ERROR (blocks save)", bool(alerts) and alerts[0]["severity"] == "ERROR")
check("Module I marks the report blocking", data(r)["summary"]["blocking"] is True)

r = c.post("/dispenses/validate", json=dispense_body(NDC_A, "RX-A1"), headers=H)
alerts = [a for a in data(r).get("alerts", []) if a.get("code") == "NO_INVENTORY_FOR_DISPENSE"]
check("Module I silent when stock exists", len(alerts) == 0, json.dumps(alerts)[:200])

r = c.post("/dispenses", json=dispense_body(NDC_B, "RX-B1"), headers=H)
check("save BLOCKED (422) when no inventory", r.status_code == 422, str(r.status_code))
r = c.post("/dispenses", json=dispense_body(NDC_B, "RX-B1", force=True), headers=H)
check("force_save overrides Module I", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:200])
forced_report = data(r).get("report_id")
m = inv_map()
check("force-saved dispense drove stock negative", qty(m, NDC_B) == "-10.000",
      "got " + str(qty(m, NDC_B)))

print("")
print("== C. DISPENSE SAVE -> DELETE -> RE-SAVE (rx_no constraint) ==")
r = c.post("/dispenses", json=dispense_body(NDC_A, "RX-A1"), headers=H)
check("normal dispense saves", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:200])
rep_id = data(r).get("report_id")
m = inv_map()
check("inventory -10 after dispense", qty(m, NDC_A) == "90.000", "got " + str(qty(m, NDC_A)))

r = c.post("/dispenses", json=dispense_body(NDC_A, "RX-A1"), headers=H)
check("duplicate LIVE rx_no rejected cleanly (not a 500)", r.status_code in (400, 409),
      str(r.status_code) + " " + r.text[:200])

r = c.delete("/reports/" + str(rep_id), headers=H)
check("DELETE /reports succeeds", r.status_code == 200, str(r.status_code) + " " + r.text[:200])
check("delete reports the inventory restoration",
      bool(data(r).get("inventory_updates")) and data(r).get("dispenses_removed") == 1,
      json.dumps(data(r))[:200])
m = inv_map()
check("inventory restored to 100 after report delete", qty(m, NDC_A) == "100.000",
      "got " + str(qty(m, NDC_A)))

r = c.post("/dispenses", json=dispense_body(NDC_A, "RX-A1"), headers=H)
check("RE-SAVE same rx_no after delete (the constraint fix)", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:300])

print("")
print("== D. EDIT PATH SKIPS MODULE I ==")
patch_body = dispense_body(NDC_B, "RX-B1", q="11")
r = c.patch("/dispenses", json=patch_body, headers=H)
check("PATCH not blocked by Module I on a zero-stock drug", r.status_code == 200,
      str(r.status_code) + " " + r.text[:250])

print("")
print("== E. INVENTORY ROW DELETE / REVIVE ==")
r = c.delete("/pharmacy/" + str(PH) + "/inventory/" + NDC_A, headers=HT)
check("technician BLOCKED from deleting inventory (403)", r.status_code == 403, str(r.status_code))
r = c.delete("/pharmacy/" + str(PH) + "/inventory/" + NDC_A, headers=H)
check("owner can delete an inventory row", r.status_code == 200,
      str(r.status_code) + " " + r.text[:200])
m = inv_map()
check("deleted inventory row hidden from the list", NDC_A not in m, str(list(m)))

inv2 = dict(invoice_body)
inv2["invoice_number"] = "INV-1002"
inv2["line_items"] = [{"ndc11": NDC_A, "description": "TESTDRUG", "invoiced_qty": "25"}]
r = c.post("/invoices", json=inv2, headers=H)
check("invoice after inventory delete succeeds", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:200])
inv2_id = data(r).get("invoice_id")
m = inv_map()
check("revived row starts from ZERO (25, not the old balance)", qty(m, NDC_A) == "25.000",
      "got " + str(qty(m, NDC_A)))

print("")
print("== F. INVOICE DELETE -> INVENTORY REVERSAL ==")
r = c.delete("/invoices/" + str(inv_id), headers=H)
check("DELETE /invoices succeeds", r.status_code == 200, str(r.status_code) + " " + r.text[:200])
m = inv_map()
check("invoice delete removed its 100 units", qty(m, NDC_A) == "-75.000",
      "got " + str(qty(m, NDC_A)))
r = c.get("/invoices/" + str(inv_id), headers=H)
check("deleted invoice 404s", r.status_code == 404, str(r.status_code))
r = c.delete("/invoices/" + str(inv_id), headers=H)
check("double-delete is a clean 404, not a double reversal", r.status_code == 404, str(r.status_code))

print("")
print("== G. AUDIT DISMISS / RESTORE ==")
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
ve = data(r)["validation_errors"]
check("force-saved report appears in the audit report",
      any(v["report_id"] == forced_report for v in ve), str(len(ve)) + " rows")
check("audit rows default to dismissed=False", all(v["dismissed"] is False for v in ve))

r = c.post("/pharmacy/" + str(PH) + "/audit-report/dismiss",
           json={"kind": "validation", "refs": [str(forced_report)]}, headers=H)
check("dismiss succeeds", r.status_code == 200, str(r.status_code) + " " + r.text[:200])
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
check("dismissed row hidden by default",
      not any(v["report_id"] == forced_report for v in data(r)["validation_errors"]))
r = c.get("/pharmacy/" + str(PH) + "/audit-report?include_dismissed=true", headers=H)
rows = [v for v in data(r)["validation_errors"] if v["report_id"] == forced_report]
check("include_dismissed shows it, flagged dismissed=True",
      bool(rows) and rows[0]["dismissed"] is True)

r = c.post("/pharmacy/" + str(PH) + "/audit-report/dismiss",
           json={"kind": "validation", "refs": [str(forced_report)]}, headers=H)
check("re-dismiss is idempotent (no 500)", r.status_code == 200,
      str(r.status_code) + " " + r.text[:150])
r = c.post("/pharmacy/" + str(PH) + "/audit-report/restore",
           json={"kind": "validation", "refs": [str(forced_report)]}, headers=H)
check("restore succeeds", r.status_code == 200, str(r.status_code) + " " + r.text[:150])
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
check("restored row is back in the default view",
      any(v["report_id"] == forced_report for v in data(r)["validation_errors"]))
r = c.post("/pharmacy/" + str(PH) + "/audit-report/dismiss",
           json={"kind": "validation", "refs": [str(forced_report)]}, headers=H)
check("dismiss AGAIN after restore (unique-key row reuse)", r.status_code == 200,
      str(r.status_code) + " " + r.text[:200])

print("")
print("=" * 62)
failed = [x for x in results if not x[1]]
print("TOTAL " + str(len(results)) + "  PASSED " + str(len(results) - len(failed)) +
      "  FAILED " + str(len(failed)))
for n, _, d in failed:
    print("  FAILED: " + n + "  -- " + str(d))
sys.exit(1 if failed else 0)
