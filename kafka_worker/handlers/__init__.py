"""
kafka_worker/handlers
─────────────────────
One handler per ProcessType. Each handler is an ASYNC callable

    async def handler(session: AsyncSession, doc: Document, *,
                      medical_store_id: int, batch_id: int | None) -> dict

The base worker awaits the handler on the event loop. CPU/IO bound
extraction inside each handler is wrapped in `asyncio.to_thread`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from core.enums import ProcessType
from kafka_worker.handlers.barcode_handler import handle_barcode
from kafka_worker.handlers.dispense_handler import handle_dispense
from kafka_worker.handlers.invoice_handler import handle_invoice

HandlerFn = Callable[..., Awaitable[dict]]

HANDLERS: dict[ProcessType, HandlerFn] = {
    ProcessType.INVOICE: handle_invoice,
    ProcessType.DISPENSE: handle_dispense,
    ProcessType.BARCODE: handle_barcode,
}


def get_handler(process_type: ProcessType) -> HandlerFn:
    handler = HANDLERS.get(process_type)
    if handler is None:
        raise ValueError(f"No handler registered for process type: {process_type}")
    return handler
