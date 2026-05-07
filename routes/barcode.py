import base64
import traceback
from fastapi import APIRouter, UploadFile, File, HTTPException
from services.llm_vision_barcode_processor import BarcodeProcessorService
from loguru import logger

router = APIRouter(prefix="/barcode", tags=["Barcode Processing"])

# Initialize the processor service
processor = BarcodeProcessorService(model_name="qwen3.5:latest")

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
