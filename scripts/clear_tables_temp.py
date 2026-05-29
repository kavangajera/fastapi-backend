"""Temporary helper to clear invoice/report/reconciliation tables."""

from pathlib import Path
import sys

from sqlalchemy import delete
from sqlalchemy.orm import Session

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT_DIR))

from database import SessionLocal
from models import Invoice, InvoiceLineItem, InvoiceSummary
from models import DrugReport, Medicine, Dispense
from models import DispenseReconciliation


def clear_tables() -> None:
    db: Session = SessionLocal()
    try:
        db.execute(delete(InvoiceLineItem))
        db.execute(delete(InvoiceSummary))
        db.execute(delete(Invoice))
        db.execute(delete(DispenseReconciliation))
        db.execute(delete(Dispense))
        db.execute(delete(Medicine))
        db.execute(delete(DrugReport))
        db.commit()
        print("Cleared invoice, report, dispense, and reconciliation tables.")
    finally:
        db.close()


if __name__ == "__main__":
    clear_tables()
