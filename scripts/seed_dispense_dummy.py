from decimal import Decimal, InvalidOperation
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func

from database import SessionLocal
from models import Dispense, DispenseReconciliation, DrugReport, InvoiceLineItem, Medicine


def _to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None


def _to_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def _sum_invoice_qty(items: list[InvoiceLineItem]) -> Decimal | None:
    total = Decimal("0")
    has_value = False
    for item in items:
        qty = _to_decimal(item.invoiced_qty)
        if qty is None:
            continue
        total += qty
        has_value = True
    return total if has_value else None


def clear_dispense_data(db) -> None:
    db.query(DispenseReconciliation).delete(synchronize_session=False)
    db.query(Dispense).delete(synchronize_session=False)
    db.query(Medicine).delete(synchronize_session=False)
    db.query(DrugReport).delete(synchronize_session=False)
    db.commit()


def seed_from_hardcoded() -> int:
    db = SessionLocal()
    try:
        clear_dispense_data(db)

        db_report = DrugReport(
            pharmacy_name="Sunrise Care Pharmacy",
            pharmacy_address=None,
            pharmacy_phone=None,
            pharmacy_fax=None,
            report_date="05/28/2026",
            report_from_date="05/28/2026",
            report_to_date="05/28/2026",
            grand_total_rx_count=41,
            grand_total_price=Decimal("4202.00"),
            grand_total_cost=None,
        )
        db.add(db_report)
        db.flush()

        medicines = [
            {
                "drug_name": "Amoxicillin 500mg Capsules",
                "ndc": "68382009501",
                "qty_disp": "84",
                "rx_count": 11,
                "ins_paid": "861.00",
                "total_price": "1050.00",
            },
            {
                "drug_name": "Metformin HCL 1000mg Tablets",
                "ndc": "50742062201",
                "qty_disp": "145",
                "rx_count": 16,
                "ins_paid": "1058.41",
                "total_price": "1290.50",
            },
            {
                "drug_name": "Atorvastatin 20mg Tablets",
                "ndc": "69452031220",
                "qty_disp": "96",
                "rx_count": 14,
                "ins_paid": "1239.84",
                "total_price": "1512.00",
            },
            {
                "drug_name": "Sterile Gloves Box",
                "ndc": "4217",
                "qty_disp": "21",
                "rx_count": None,
                "ins_paid": "0.00",
                "total_price": "115.50",
            },
            {
                "drug_name": "Digital Thermometer",
                "ndc": "8842",
                "qty_disp": "13",
                "rx_count": None,
                "ins_paid": "0.00",
                "total_price": "234.00",
            },
        ]

        for med_data in medicines:
            db_med = Medicine(
                report_id=db_report.id,
                drug_name=med_data["drug_name"],
                ndc=str(med_data["ndc"]),
                inventory_bucket=None,
                lot_no_exp_date=None,
                total_packs=None,
                total_rx_count=med_data["rx_count"],
                total_ins_paid=_to_decimal(med_data["ins_paid"]),
                total_price=_to_decimal(med_data["total_price"]),
                total_cost=None,
            )
            db.add(db_med)
            db.flush()

            dispenses = [
                Dispense(
                    medicine_id=db_med.id,
                    qty_disp=_to_decimal(med_data["qty_disp"]),
                    qty_ord=None,
                    days_supply=None,
                    date_filled="05/28/2026",
                    rx_no=None,
                    ref=None,
                    pat_name=None,
                    pat_addr=None,
                    pat_phone=None,
                    pres_name=None,
                    pres_addr=None,
                    pres_phone=None,
                    price=_to_decimal(med_data["total_price"]),
                    ins_paid=_to_decimal(med_data["ins_paid"]),
                    ins_code=None,
                )
            ]

            db.bulk_save_objects(dispenses)

        db.commit()
        db.refresh(db_report)


        # Collect all unique ndc and upc codes from medicines
        report_codes = set()
        for med in medicines:
            ndc = str(med.get("ndc")) if med.get("ndc") else None
            if ndc:
                report_codes.add(ndc)

        # Also add all unique UPCs from InvoiceLineItem that are not in ndc11
        invoice_upcs = db.query(InvoiceLineItem.upc).filter(InvoiceLineItem.upc != None).distinct().all()
        for (upc,) in invoice_upcs:
            if upc and upc not in report_codes:
                report_codes.add(upc)

        for code in report_codes:
            # Try to match by ndc11 first, then by upc if not found
            dispensed_qty = (
                db.query(func.sum(Dispense.qty_disp))
                .join(Medicine, Medicine.id == Dispense.medicine_id)
                .filter(Medicine.report_id == db_report.id, Medicine.ndc == code)
                .scalar()
            )

            # Prefer ndc11 match, fallback to upc
            invoice_items = db.query(InvoiceLineItem).filter(
                (InvoiceLineItem.ndc11 == code) | (InvoiceLineItem.upc == code)
            ).all()
            invoice_qty = _sum_invoice_qty(invoice_items)

            remaining_qty = None
            if invoice_qty is not None and dispensed_qty is not None:
                remaining_qty = invoice_qty - dispensed_qty

            db.add(
                DispenseReconciliation(
                    report_id=db_report.id,
                    ndc11=code,
                    invoice_qty=invoice_qty,
                    dispensed_qty=dispensed_qty,
                    remaining_qty=remaining_qty,
                )
            )

        db.commit()
        return db_report.id
    finally:
        db.close()


if __name__ == "__main__":
    report_id = seed_from_hardcoded()
    print(f"Seeded hardcoded report. report_id={report_id}")
