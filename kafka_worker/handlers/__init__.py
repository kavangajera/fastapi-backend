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

HandlerFn = Callable[..., Awaitable[dict]]


def get_handler(process_type: ProcessType) -> HandlerFn:
    # Import only the selected worker's native dependencies. In particular,
    # dispense and invoice workers must not require the system zbar DLL.
    if process_type == ProcessType.DISPENSE:
        from kafka_worker.handlers.dispense_handler import handle_dispense

        return handle_dispense
    if process_type == ProcessType.INVOICE:
        from kafka_worker.handlers.invoice_handler import handle_invoice

        return handle_invoice
    if process_type == ProcessType.BARCODE:
        from kafka_worker.handlers.barcode_handler import handle_barcode

        return handle_barcode
    raise ValueError(f"No handler registered for process type: {process_type}")
