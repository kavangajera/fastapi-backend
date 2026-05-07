import base64
import json
import requests
from typing import Optional, Dict, Any
from pydantic import BaseModel
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage
from loguru import logger

class ExtractedBarcodeData(BaseModel):
    ndc: Optional[str] = None
    exp: Optional[str] = None
    lot: Optional[str] = None
    sn: Optional[str] = None
    gtin: Optional[str] = None

class BarcodeProcessorService:
    def __init__(self, model_name: str = "qwen3.5:latest"):
        self.model_name = model_name
        # format="json" ensures the output is constrained to valid JSON
        self.llm = ChatOllama(model=self.model_name, temperature=0, format="json")

    def format_to_product_ndc(self, ndc: str) -> str:
        """
        Converts a 10-digit package NDC to hyphenated product NDC format.
        Example: 6838209505 -> 68382-095
        """
        if not ndc:
            return ""
        # Remove any existing formatting
        clean_ndc = ndc.replace("-", "").strip()
        # If it's 10 digits or more, use the standard conversion logic: first 5, hyphen, next 3
        if len(clean_ndc) >= 10:
            return f"{clean_ndc[:5]}-{clean_ndc[5:8]}"
        
        return ndc

    def process_barcode_image(self, image_path: str) -> Dict[str, Any]:
        """
        Process a local image file to extract barcode details and fetch FDA info.
        """
        with open(image_path, "rb") as image_file:
            image_base64 = base64.b64encode(image_file.read()).decode("utf-8")
        
        return self.process_barcode_base64(image_base64)

    def process_barcode_base64(self, image_base64: str) -> Dict[str, Any]:
        """
        Process a base64 encoded image to extract barcode details and fetch FDA info.
        """
        prompt = """
        Analyze the provided image of a medication barcode/package.
        Extract the following details and return ONLY a structured JSON response with these exact keys:
        - ndc (string, full numbers from NDC if found)
        - exp (string, expiration date)
        - lot (string, lot number)
        - sn (string, serial number)
        - gtin (string, Global Trade Item Number)
        
        If any value is not found, use null or an empty string.
        Ensure the output is strictly valid JSON.
        """
        
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"},
                },
            ]
        )
        
        logger.info(f"Invoking LLM ({self.model_name}) with image payload for barcode extraction...")
        response = self.llm.invoke([message])
        logger.debug(f"Raw LLM response: {response.content}")
        
        try:
            content = response.content.strip()
            # Handle potential markdown code block formatting
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            extracted_data = json.loads(content)
            logger.info(f"Successfully parsed LLM JSON response: {extracted_data}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode JSON from LLM response: {e}")
            extracted_data = {}
            
        original_ndc = str(extracted_data.get("ndc", "")).strip()
        
        # Fallback: if NDC is not found but GTIN is, we can often derive it.
        # US NDCs are typically 10 digits.
        # A 14-digit GTIN-14 (e.g. 00375907005305) contains the NDC at digits 4-13.
        # A 12-digit UPC (e.g. 375907005305) contains the NDC at digits 2-11.
        if not original_ndc and extracted_data.get("gtin"):
            gtin = str(extracted_data.get("gtin", "")).strip()
            if len(gtin) == 14 and gtin.isdigit():
                original_ndc = gtin[3:13]
                logger.info(f"Derived NDC {original_ndc} from 14-digit GTIN {gtin}")
            elif len(gtin) == 12 and gtin.isdigit():
                original_ndc = gtin[1:11]
                logger.info(f"Derived NDC {original_ndc} from 12-digit UPC/GTIN {gtin}")
                
        logger.info(f"Original NDC extracted/derived: {original_ndc}")
        
        product_ndc = self.format_to_product_ndc(str(original_ndc)) if original_ndc else ""
        logger.info(f"Formatted product NDC: {product_ndc}")
        
        fda_data = None
        if product_ndc:
            fda_url = f'https://api.fda.gov/drug/ndc.json?search=product_ndc:"{product_ndc}"'
            logger.info(f"Querying FDA API: {fda_url}")
            try:
                fda_resp = requests.get(fda_url)
                logger.info(f"FDA API response status: {fda_resp.status_code}")
                if fda_resp.status_code == 200:
                    fda_data = fda_resp.json()
                else:
                    logger.warning(f"FDA API returned non-200 status: {fda_resp.status_code} - {fda_resp.text}")
                    fda_data = {"error": f"FDA API returned status {fda_resp.status_code}", "details": fda_resp.text}
            except Exception as e:
                logger.error(f"Error querying FDA API: {e}")
                fda_data = {"error": str(e)}
                
        logger.info("Barcode processing complete.")
        # Update the extracted data dict so the client sees the derived NDC
        if original_ndc:
            extracted_data["ndc"] = original_ndc
            
        return {
            "extracted_data": extracted_data,
            "product_ndc": product_ndc,
            "fda_data": fda_data
        }

if __name__ == "__main__":
    import sys
    import os
    
    processor = BarcodeProcessorService()
    # Default to the image in the root directory if not specified
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_image = os.path.join(base_dir, "image.png")
    
    image_to_test = sys.argv[1] if len(sys.argv) > 1 else default_image
    
    try:
        result = processor.process_barcode_image(image_to_test)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error processing image: {e}")
