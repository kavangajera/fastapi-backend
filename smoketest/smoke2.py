"""Smoke test part 2: documents / pending queue, and the temperature device flow."""
import sys
import uuid

import httpx

BASE = "http://127.0.0.1:5099"
OWNER = sys.argv[1]
PH = int(sys.argv[2])
H = {"Authorization": "Bearer " + OWNER}
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


def pending_keys():
    r = c.get("/reports/?limit=200", headers=H)
    rows = data(r)
    if not isinstance(rows, list):
        return []
    return [x["doc_key"] for x in rows if x.get("kind") == "pending_document"]


NDC = "00002322730"

print("")
print("== H. DOCUMENTS / PENDING QUEUE ==")

# Two documents seeded straight into the DB (Kafka isn't running here).
import asyncio  # noqa: E402
import os  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.async_db import AsyncSessionLocal  # noqa: E402
from core.enums import DocumentStatus, ProcessType  # noqa: E402
from models.document import Document  # noqa: E402

DK_SAVED = uuid.uuid4().hex
DK_LOOSE = uuid.uuid4().hex
DK_FAILED = uuid.uuid4().hex


async def seed_docs():
    async with AsyncSessionLocal() as db:
        for dk, st in ((DK_SAVED, DocumentStatus.COMPLETED.value),
                       (DK_LOOSE, DocumentStatus.COMPLETED.value),
                       (DK_FAILED, DocumentStatus.FAILED_PERMANENTLY.value)):
            db.add(Document(
                doc_key=dk, medical_store_id=PH, uploaded_by_user_id=1,
                document_type="pdf", process_type=ProcessType.DISPENSE.value,
                original_filename=dk[:8] + ".pdf", storage_path="/tmp/" + dk,
                file_size=10, status=st,
                error_message="boom" if st.startswith("FAILED") else None,
            ))
        await db.commit()
        return True


asyncio.run(seed_docs())
doc_ids = {}


async def doc_id_of(dk):
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(Document.id).where(Document.doc_key == dk))).scalar_one()


for dk in (DK_SAVED, DK_LOOSE, DK_FAILED):
    doc_ids[dk] = asyncio.run(doc_id_of(dk))

keys = pending_keys()
check("uploaded docs appear in the pending queue", DK_SAVED in keys and DK_LOOSE in keys,
      str(len(keys)) + " pending")

# Save a report FROM one of them.
body = {
    "medical_store_id": PH, "document_id": doc_ids[DK_SAVED], "force_save": True,
    "pharmacy": {"report_from_date": "2026-03-01", "report_to_date": "2026-03-31"},
    "grand_total": {"total_rx_count": 1, "total_price": "20.00"},
    "medicines": [{"drug_name": "TESTDRUG", "ndc": NDC, "dispenses": [
        {"qty_disp": "5", "rx_no": "RX-DOC-1", "date_filled": "03/15/2026",
         "days_supply": "30", "pat_name": "DOE, JANE", "price": "20.00",
         "ins_paid": "20.00", "ins_code": "01"}]}],
}
r = c.post("/dispenses", json=body, headers=H)
check("save a report from a queued document", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:200])
rep_id = data(r).get("report_id")
check("saved document leaves the pending queue", DK_SAVED not in pending_keys())

r = c.delete("/documents/" + DK_SAVED, headers=H)
check("discarding an already-saved document is refused (409)", r.status_code == 409,
      str(r.status_code) + " " + r.text[:200])

# THE regression the user reported: deleting the report must not resurrect its upload.
r = c.delete("/reports/" + str(rep_id), headers=H)
check("delete the report", r.status_code == 200, str(r.status_code) + " " + r.text[:150])
check("deleted report does NOT resurrect its document in the queue",
      DK_SAVED not in pending_keys(), str(pending_keys()))

r = c.delete("/documents/" + DK_SAVED, headers=H)
check("that document is now discardable (report is gone)", r.status_code == 200,
      str(r.status_code) + " " + r.text[:200])

r = c.delete("/documents/" + DK_LOOSE, headers=H)
check("discard a plain queued upload", r.status_code == 200,
      str(r.status_code) + " " + r.text[:150])
check("discarded upload leaves the queue", DK_LOOSE not in pending_keys())
r = c.get("/documents/" + DK_LOOSE, headers=H)
check("discarded document 404s", r.status_code == 404, str(r.status_code))

# Parsing-failure dismissal in the audit report.
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
pe = [p for p in data(r)["parsing_errors"] if p["doc_key"] == DK_FAILED]
check("failed document appears as a parsing error", len(pe) == 1, str(len(data(r)["parsing_errors"])))
r = c.post("/pharmacy/" + str(PH) + "/audit-report/dismiss",
           json={"kind": "parsing", "refs": [DK_FAILED]}, headers=H)
check("dismiss a parsing failure", r.status_code == 200, str(r.status_code) + " " + r.text[:150])
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
check("dismissed parsing row hidden",
      not any(p["doc_key"] == DK_FAILED for p in data(r)["parsing_errors"]))
r = c.get("/pharmacy/" + str(PH) + "/audit-report?include_dismissed=true", headers=H)
rows = [p for p in data(r)["parsing_errors"] if p["doc_key"] == DK_FAILED]
check("parsing row flagged dismissed=True", bool(rows) and rows[0]["dismissed"] is True)
check("the underlying document is UNTOUCHED by the dismissal",
      c.get("/documents/" + DK_FAILED, headers=H).status_code == 200)
r = c.post("/pharmacy/" + str(PH) + "/audit-report/restore",
           json={"kind": "parsing", "refs": [DK_FAILED]}, headers=H)
check("restore the parsing row", r.status_code == 200, str(r.status_code))
r = c.get("/pharmacy/" + str(PH) + "/audit-report", headers=H)
check("restored parsing row is back",
      any(p["doc_key"] == DK_FAILED for p in data(r)["parsing_errors"]))

print("")
print("== I. TEMPERATURE DEVICE FLOW ==")
r = c.post("/temperature-devices",
           json={"medical_store_id": PH, "nickname": "Vaccine Fridge A"}, headers=H)
check("register a temperature device", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:250])
reg = data(r)
secret = reg.get("device_secret") if isinstance(reg, dict) else None
dev_id = reg.get("device", {}).get("temperature_device_id") if isinstance(reg, dict) else None
check("secret returned exactly once at registration", bool(secret), str(reg)[:200])

r = c.post("/temperature-devices/logging/start", json={"device_secret": secret})
check("start logging with the secret (no user auth)", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:250])
tok = data(r).get("access_token") if isinstance(data(r), dict) else None
check("session token issued", bool(tok), str(data(r))[:200])
DH = {"Authorization": "Bearer " + str(tok)}

r = c.post("/temperature-logs", json=[{"temp": 4.2, "time": "2026-03-15T10:00:00"},
                                      {"temperature": 25.5}], headers=DH)
check("device pushes a batch of readings", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:250])

r = c.get("/temperature-logs?medical_store_id=" + str(PH) + "&limit=50", headers=H)
logs = data(r)
items = logs.get("items", logs) if isinstance(logs, dict) else logs
check("readings are readable by the owner", isinstance(items, list) and len(items) >= 2,
      str(logs)[:200])
statuses = [i.get("status") for i in items] if isinstance(items, list) else []
check("status derived from the safe range (one OK, one out-of-range)",
      len(set(s for s in statuses if s)) >= 2, str(statuses))

r = c.post("/temperature-devices/logging/token", json={"device_secret": secret})
check("renewing issues a replacement token", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:200])
tok2 = data(r).get("access_token") if isinstance(data(r), dict) else None
r = c.post("/temperature-logs", json=[{"temp": 5.0}], headers=DH)
check("the OLD token is revoked by the renewal", r.status_code == 401,
      str(r.status_code) + " " + r.text[:150])
r = c.post("/temperature-logs", json=[{"temp": 5.0}],
           headers={"Authorization": "Bearer " + str(tok2)})
check("the NEW token works", r.status_code in (200, 201),
      str(r.status_code) + " " + r.text[:150])

r = c.post("/temperature-devices/logging/stop", json={"device_secret": secret})
check("stop logging", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:200])
r = c.post("/temperature-logs", json=[{"temp": 5.0}],
           headers={"Authorization": "Bearer " + str(tok2)})
check("stopping revokes the live token immediately", r.status_code == 401,
      str(r.status_code) + " " + r.text[:150])
r = c.post("/temperature-devices/logging/stop", json={"device_secret": secret})
check("stop is idempotent", r.status_code in (200, 201), str(r.status_code))

r = c.post("/temperature-devices/logging/token", json={"device_secret": secret})
check("renew with no open session is refused (409)", r.status_code == 409,
      str(r.status_code) + " " + r.text[:150])
r = c.post("/temperature-devices/logging/start", json={"device_secret": "not-a-real-secret"})
check("a bogus secret is rejected", r.status_code in (401, 403, 404),
      str(r.status_code) + " " + r.text[:150])

if dev_id:
    r = c.get("/temperature-devices/" + str(dev_id) + "/sessions", headers=H)
    check("session history is readable", r.status_code == 200, str(r.status_code))
    r = c.delete("/temperature-devices/" + str(dev_id), headers=H)
    check("device can be deleted", r.status_code == 200, str(r.status_code) + " " + r.text[:150])
    r = c.post("/temperature-devices/logging/start", json={"device_secret": secret})
    check("a deleted device cannot start logging", r.status_code in (401, 403, 404),
          str(r.status_code) + " " + r.text[:150])

print("")
print("=" * 62)
failed = [x for x in results if not x[1]]
print("TOTAL " + str(len(results)) + "  PASSED " + str(len(results) - len(failed)) +
      "  FAILED " + str(len(failed)))
for n, _, d in failed:
    print("  FAILED: " + n + "  -- " + str(d))
sys.exit(1 if failed else 0)
