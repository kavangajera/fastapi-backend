import asyncio
import base64
from datetime import date, datetime
from zoneinfo import ZoneInfo
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, status, Depends
from loguru import logger
from sqlalchemy.orm import Session

from core.config import settings
from database import get_db
from models import InvoiceLineItem
from services.barcode_scanner import BarcodeScannerService
from services.datamatrix_scanner import scan_image_bytes
from services.ndc_utils import digits_only, ndc10_to_ndc11_from_package_ndc

router = APIRouter(prefix="/barcode", tags=["Barcode Processing"])

# Initialize the processor service
processor = BarcodeScannerService()
_barcode_processing_lock = asyncio.Lock()

@router.post("/process-image")
async def process_barcode_image(file: UploadFile = File(...)):
    """
    Upload an image of a medication barcode/package to extract NDC, Expiration, Lot, Serial Number, and GTIN.
    Also returns matching FDA product data.
    """
    if not file.content_type.startswith("image/"):
        logger.warning(f"Invalid file upload type: {file.content_type}")
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")
    
    try:
        logger.info(f"Processing uploaded image: {file.filename} ({file.content_type})")
        contents = await file.read()
        image_base64 = base64.b64encode(contents).decode("utf-8")
        
        result = processor.process_barcode_base64(image_base64)
        return {
            "status_code": 200,
            "message": "Image processed successfully",
            "data": result
        }
    except Exception as e:
        logger.exception(f"Error processing barcode image: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")


def _extract_package_ndc(fda_data: Optional[dict]) -> Optional[str]:
    if not isinstance(fda_data, dict):
        return None

    results = fda_data.get("results") or []
    for result in results:
        packaging = result.get("packaging") or []
        for pack in packaging:
            package_ndc = pack.get("package_ndc")
            if package_ndc:
                return package_ndc
    return None


def _pick_datamatrix_payload(dm_payload: dict) -> Optional[dict]:
    if not dm_payload:
        return None
    if dm_payload.get("error"):
        return None
    items = dm_payload.get("detected_items")
    if isinstance(items, list) and items:
        return items[0]
    return dm_payload


def _parse_dm_expiry(expiry_value: Optional[str]) -> Optional[date]:
    if not expiry_value:
        return None
    try:
        return date.fromisoformat(expiry_value)
    except ValueError:
        return None


@router.post(
    "/verify-batch",
    status_code=status.HTTP_200_OK,
    summary="Verify invoice items using barcode + datamatrix images",
)
async def verify_batch_images(
    files: List[UploadFile] = File(..., description="Batch of images"),
    db: Session = Depends(get_db),
):
    if len(files) > settings.BARCODE_MAX_FILES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Max {settings.BARCODE_MAX_FILES} images allowed per request.",
        )

    async with _barcode_processing_lock:
        pending_barcode = []
        pending_datamatrix = []
        updated_items = 0
        unmatched = []

        for file in files:
            if not file.content_type or not file.content_type.startswith("image/"):
                raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

            image_bytes = await file.read()
            if not image_bytes:
                raise HTTPException(status_code=400, detail="Uploaded image is empty.")

            image_base64 = base64.b64encode(image_bytes).decode("utf-8")
            barcode_result = processor.process_barcode_base64(image_base64)
            dm_result = scan_image_bytes(
                image_bytes,
                debug=settings.DATAMATRIX_DEBUG,
                debug_dir=settings.DATAMATRIX_DEBUG_DIR,
                filename=file.filename,
            )

            barcode_data = barcode_result.get("extracted_data") or {}
            dm_payload = _pick_datamatrix_payload(dm_result)
            if dm_result.get("error"):
                logger.info("DataMatrix scan: {filename} -> {error}", filename=file.filename, error=dm_result.get("error"))
            elif dm_payload:
                logger.info(
                    "DataMatrix scan: {filename} gtin={gtin} serial={serial} exp={exp} lot={lot}",
                    filename=file.filename,
                    gtin=dm_payload.get("gtin"),
                    serial=dm_payload.get("serial_number"),
                    exp=dm_payload.get("expiration_date"),
                    lot=dm_payload.get("lot_number"),
                )
            else:
                logger.info("DataMatrix scan: {filename} -> no data", filename=file.filename)

            has_barcode = bool(barcode_data.get("ndc"))
            has_dm = bool(dm_payload)

            def _pair_and_update(barcode_info: dict, dm_info: dict, fda_data: Optional[dict], filename: str):
                nonlocal updated_items

                fda_package_ndc = _extract_package_ndc(fda_data)
                fda_ndc11 = ndc10_to_ndc11_from_package_ndc(fda_package_ndc) if fda_package_ndc else None

                raw_ndc = barcode_info.get("ndc")
                ndc_digits = digits_only(raw_ndc)
                ndc11 = fda_ndc11 or (ndc_digits if len(ndc_digits) == 11 else None)
                if fda_ndc11:
                    logger.opt(colors=True).info(
                        "<green>OK</green> BARCODE_OK: {filename} ndc10={ndc10} -> ndc11={ndc11}",
                        filename=filename,
                        ndc10=fda_package_ndc,
                        ndc11=fda_ndc11,
                    )

                if not ndc11:
                    unmatched.append(
                        {
                            "filename": filename,
                            "reason": "No NDC11 could be derived.",
                        }
                    )
                    return

                expiry_date = _parse_dm_expiry(dm_info.get("expiration_date"))
                today = datetime.now(ZoneInfo(settings.APP_TIMEZONE)).date()
                fda_ok = bool(fda_package_ndc)
                expiry_ok = bool(expiry_date and expiry_date > today)
                verified = fda_ok and expiry_ok

                update_payload = {
                    "fda_package_ndc": fda_package_ndc,
                    "fda_ndc11": fda_ndc11,
                    "dm_gtin": dm_info.get("gtin"),
                    "dm_serial_number": dm_info.get("serial_number"),
                    "dm_expiration_date": dm_info.get("expiration_date"),
                    "dm_lot_number": dm_info.get("lot_number"),
                    "verified": verified,
                }

                updated = (
                    db.query(InvoiceLineItem)
                    .filter(InvoiceLineItem.ndc11 == ndc11)
                    .update(update_payload, synchronize_session=False)
                )

                if updated == 0:
                    unmatched.append(
                        {
                            "filename": filename,
                            "ndc11": ndc11,
                            "reason": "No matching invoice line item.",
                        }
                    )
                    logger.info(
                        "MATCH_FAIL: {filename} ndc11={ndc11} no invoice match",
                        filename=filename,
                        ndc11=ndc11,
                    )
                else:
                    updated_items += updated
                    logger.opt(colors=True).info(
                        "<green>OK</green> MATCH_OK: {filename} ndc11={ndc11} updated={count}",
                        filename=filename,
                        ndc11=ndc11,
                        count=updated,
                    )

            if has_barcode and has_dm:
                _pair_and_update(barcode_data, dm_payload, barcode_result.get("fda_data"), file.filename)
            elif has_barcode:
                if pending_datamatrix:
                    dm_payload = pending_datamatrix.pop(0)
                    _pair_and_update(
                        barcode_data,
                        dm_payload["payload"],
                        barcode_result.get("fda_data"),
                        file.filename,
                    )
                else:
                    pending_barcode.append(
                        {
                            "barcode": barcode_data,
                            "fda_data": barcode_result.get("fda_data"),
                            "filename": file.filename,
                        }
                    )
            elif has_dm:
                if pending_barcode:
                    barcode_bundle = pending_barcode.pop(0)
                    _pair_and_update(
                        barcode_bundle["barcode"],
                        dm_payload,
                        barcode_bundle["fda_data"],
                        barcode_bundle["filename"],
                    )
                else:
                    pending_datamatrix.append({"payload": dm_payload, "filename": file.filename})
            else:
                unmatched.append(
                    {
                        "filename": file.filename,
                        "reason": "No barcode or datamatrix detected.",
                    }
                )

        for leftover in pending_barcode:
            raw_ndc = leftover["barcode"].get("ndc")
            ndc_digits = digits_only(raw_ndc)
            ndc11 = ndc_digits if len(ndc_digits) == 11 else None
            if not ndc11:
                unmatched.append(
                    {
                        "filename": leftover.get("filename"),
                        "reason": "Unpaired barcode with no NDC11.",
                    }
                )
                continue

            updated = (
                db.query(InvoiceLineItem)
                .filter(InvoiceLineItem.ndc11 == ndc11)
                .update({"fda_ndc11": None}, synchronize_session=False)
            )
            if updated == 0:
                unmatched.append(
                    {
                        "filename": leftover.get("filename"),
                        "ndc11": ndc11,
                        "reason": "Unpaired barcode had no invoice match.",
                    }
                )
            else:
                updated_items += updated

        for leftover in pending_datamatrix:
            unmatched.append(
                {
                    "filename": leftover.get("filename"),
                    "reason": "Unpaired datamatrix.",
                    "datamatrix": leftover.get("payload"),
                }
            )

        db.commit()

    return {
        "updated_items": updated_items,
        "unmatched": unmatched,
    }
