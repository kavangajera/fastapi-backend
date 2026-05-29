import asyncio
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from loguru import logger
from sqlalchemy.orm import Session, selectinload

from core.config import settings
from database import get_db
from models import Invoice
from schemas.invoice import InvoiceResponse, InvoiceUploadSummary
from services.invoice_service import count_pdf_pages, extract_invoice_from_pdf, store_invoice

router = APIRouter(prefix="/invoices", tags=["Invoices"])

_invoice_processing_lock = asyncio.Lock()


@router.post(
    "/upload",
    response_model=InvoiceUploadSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Upload invoices (PDF)",
)
async def upload_invoices(
    files: List[UploadFile] = File(..., description="Up to 10 PDF invoices"),
    db: Session = Depends(get_db),
):
    if len(files) > settings.INVOICE_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Max {settings.INVOICE_MAX_FILES} PDFs allowed per request.",
        )

    async with _invoice_processing_lock:
        invoices_created = 0
        line_items_created = 0

        for file in files:
            if not file.filename or not file.filename.lower().endswith(".pdf"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only PDF invoices are supported.",
                )

            file_bytes = await file.read()
            if not file_bytes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Uploaded file is empty.",
                )

            page_count = count_pdf_pages(file_bytes)
            if page_count > settings.INVOICE_MAX_PAGES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invoice exceeds {settings.INVOICE_MAX_PAGES} pages: "
                        f"{file.filename} has {page_count} pages."
                    ),
                )

            logger.info(
                "Invoice upload started: {filename} pages={pages}",
                filename=file.filename,
                pages=page_count,
            )

            try:
                invoice_payload = extract_invoice_from_pdf(file_bytes, file.filename)
                store_invoice(db, invoice_payload, file.filename, page_count)
                db.commit()

                invoices_created += 1
                line_items_created += len(invoice_payload.line_items)
            except Exception as exc:
                db.rollback()
                logger.exception("Invoice processing failed: {error}", error=exc)
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invoice processing failed: {exc}",
                )

    return InvoiceUploadSummary(
        invoices_created=invoices_created,
        line_items_created=line_items_created,
    )


@router.get(
    "/",
    response_model=List[InvoiceResponse],
    summary="List invoices",
)
def list_invoices(
    skip: int = 0,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    return (
        db.query(Invoice)
        .options(selectinload(Invoice.line_items), selectinload(Invoice.summary))
        .order_by(Invoice.id.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get(
    "/{invoice_id:int}",
    response_model=InvoiceResponse,
    summary="Get invoice by ID",
)
def get_invoice(invoice_id: int, db: Session = Depends(get_db)):
    invoice = (
        db.query(Invoice)
        .options(selectinload(Invoice.line_items), selectinload(Invoice.summary))
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice {invoice_id} not found.",
        )
    return invoice
