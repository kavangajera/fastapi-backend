"""
kafka_worker/handlers
─────────────────────
One handler per ProcessType. Each handler is a SYNC callable
``handler(db, doc) -> dict`` that loads the stored file, calls the
already-built service, and returns a JSON-serializable result payload.

The base worker runs handlers in a thread (asyncio.to_thread) so the
event loop stays free for Kafka heartbeats during heavy/blocking work.
"""

from __future__ import annotations

from typing import Callable

from core.enums import ProcessType
from kafka_worker.handlers.invoice_handler import handle_invoice
from kafka_worker.handlers.dispense_handler import handle_dispense
from kafka_worker.handlers.barcode_handler import handle_barcode

# Handler signature: (db: Session, doc: Document) -> dict
HANDLERS: dict[ProcessType, Callable] = {
    ProcessType.INVOICE: handle_invoice,
    ProcessType.DISPENSE: handle_dispense,
    ProcessType.BARCODE: handle_barcode,
}


def get_handler(process_type: ProcessType) -> Callable:
    handler = HANDLERS.get(process_type)
    if handler is None:
        raise ValueError(f"No handler registered for process type: {process_type}")
    return handler
