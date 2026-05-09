import base64
import json
import re
from io import BytesIO
from typing import Optional, Dict, Any
from urllib.parse import quote

import requests
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from loguru import logger
from pyzbar.pyzbar import decode

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage


class ExtractedBarcodeData(BaseModel):
    ndc: Optional[str] = None
    exp: Optional[str] = None
    lot: Optional[str] = None
    sn: Optional[str] = None
    gtin: Optional[str] = None


class BarcodeProcessorService:

    def __init__(self, model_name: str = "minicpm-v:latest"):

        self.model_name = model_name

        # Fallback vision model only
        self.llm = ChatOllama(
            model=self.model_name,
            temperature=0,
            format="json"
        )

    # =========================================================
    # IMAGE LOADING
    # =========================================================

    def load_image_from_base64(self, image_base64: str):
        # Allow data URLs like "data:image/png;base64,..." and plain base64.
        if image_base64.startswith("data:"):
            image_base64 = image_base64.split(",", 1)[-1]

        image_bytes = base64.b64decode(image_base64)

        # Register HEIC/HEIF support if available (optional dependency).
        pillow_heif = None
        try:
            import pillow_heif  # type: ignore

            pillow_heif.register_heif_opener()
        except Exception:
            pillow_heif = None

        # HEIC/HEIF detection ("ftyp" brand in ISO BMFF header).
        is_heif = (
            len(image_bytes) > 12
            and image_bytes[4:8] == b"ftyp"
            and image_bytes[8:12] in {
                b"heic",
                b"heix",
                b"hevc",
                b"hevx",
                b"mif1",
                b"msf1",
            }
        )

        if is_heif:
            if not pillow_heif:
                raise UnidentifiedImageError(
                    "HEIC/HEIF upload requires pillow-heif"
                )

            heif_file = pillow_heif.read_heif(image_bytes)
            pil_image = Image.frombytes(
                heif_file.mode,
                heif_file.size,
                heif_file.data,
                "raw",
            ).convert("RGB")
        else:
            try:
                pil_image = Image.open(
                    BytesIO(image_bytes)
                ).convert("RGB")
            except UnidentifiedImageError as exc:
                # Some clients send raw bytes that aren't base64; retry as-is.
                try:
                    pil_image = Image.open(
                        BytesIO(image_base64.encode("utf-8"))
                    ).convert("RGB")
                except Exception:
                    raise exc

        return pil_image

    def encode_pil_image_to_jpeg_base64(self, pil_image: Image.Image) -> str:
        buffer = BytesIO()
        pil_image.save(buffer, format="JPEG")
        return base64.b64encode(
            buffer.getvalue()
        ).decode("utf-8")

    # =========================================================
    # FAST BARCODE SCANNER (pyzbar)
    # =========================================================

    def scan_barcode(self, pil_image: Image.Image) -> Dict[str, Any]:

        logger.info("Scanning barcode using pyzbar...")

        extracted = {
            "ndc": None,
            "gtin": None,
            "raw_barcode": None
        }

        try:

            decoded_items = decode(pil_image)

            if not decoded_items:

                logger.warning("No barcode detected.")

                return extracted

            for item in decoded_items:

                barcode_data = (
                    item.data.decode("utf-8", errors="ignore")
                    if item.data
                    else ""
                )

                barcode_data = barcode_data.strip()

                if not barcode_data:
                    continue

                logger.info(
                    f"Detected barcode: {barcode_data}"
                )

                extracted["raw_barcode"] = barcode_data

                clean = re.sub(
                    r"[^0-9]",
                    "",
                    barcode_data
                )

                # GTIN-14
                if len(clean) == 14:

                    extracted["gtin"] = clean

                    # Derive NDC11
                    extracted["ndc"] = clean[3:14]

                # EAN-13 that represents UPC-A (leading zero)
                elif len(clean) == 13 and clean.startswith("0"):

                    upc = clean[1:]

                    extracted["gtin"] = upc

                    extracted["ndc"] = upc[1:11]

                # UPC-A / GTIN-12
                elif len(clean) == 12:

                    extracted["gtin"] = clean

                    extracted["ndc"] = clean[1:11]

                # Direct NDC
                elif len(clean) in [10, 11]:

                    extracted["ndc"] = clean

                break

        except Exception as e:

            logger.error(f"Barcode scanner failed: {e}")

        return extracted

    # =========================================================
    # NORMALIZE PACKAGE NDC
    # =========================================================

    def normalize_package_ndc(self, ndc: str) -> str:

        if not ndc:
            return ""

        clean_ndc = re.sub(r"[^0-9]", "", ndc)

        # FDA normalized 11-digit
        # Example:
        # 00597015230 -> 0597-0152-30

        if len(clean_ndc) == 11:

            return (
                f"{clean_ndc[1:5]}-"
                f"{clean_ndc[5:9]}-"
                f"{clean_ndc[9:11]}"
            )

        # 10-digit (default to 5-3-2)
        if len(clean_ndc) == 10:

            return (
                f"{clean_ndc[:5]}-"
                f"{clean_ndc[5:8]}-"
                f"{clean_ndc[8:10]}"
            )

        # Already formatted
        if ndc.count("-") == 2:
            return ndc.strip()

        return ndc.strip()

    # =========================================================
    # FALLBACK VISION LLM
    # =========================================================

    def fallback_llm_extraction(self, image_base64: str):

        logger.warning(
            "Falling back to vision LLM extraction..."
        )

        prompt = """
        Analyze the medication image.

        Return ONLY valid JSON:

        {
          "ndc": "...",
          "exp": "...",
          "lot": "...",
          "sn": "...",
          "gtin": "..."
        }

        Rules:
        - preserve leading zeros
        - no hallucinations
        - use null if missing
        """

        message = HumanMessage(
            content=[
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": (
                            f"data:image/jpeg;base64,"
                            f"{image_base64}"
                        )
                    },
                },
            ]
        )

        response = self.llm.invoke([message])

        content = response.content.strip()

        if content.startswith("```json"):
            content = content[7:]

        if content.endswith("```"):
            content = content[:-3]

        content = content.strip()

        try:

            parsed = json.loads(content)

            logger.info(
                f"LLM extraction success: {parsed}"
            )

            return parsed

        except Exception as e:

            logger.error(
                f"Failed to parse LLM JSON: {e}"
            )

            return {}

    # =========================================================
    # FDA LOOKUP
    # =========================================================

    def build_ndc_candidates(self, ndc: str) -> list[str]:
        clean_ndc = re.sub(r"[^0-9]", "", ndc or "")

        if not clean_ndc:
            return []

        if len(clean_ndc) == 11:
            return [
                f"{clean_ndc[1:5]}-{clean_ndc[5:9]}-{clean_ndc[9:11]}"
            ]

        if len(clean_ndc) == 10:
            return [
                f"{clean_ndc[:4]}-{clean_ndc[4:8]}-{clean_ndc[8:10]}",
                f"{clean_ndc[:5]}-{clean_ndc[5:8]}-{clean_ndc[8:10]}",
                f"{clean_ndc[:5]}-{clean_ndc[5:9]}-{clean_ndc[9:10]}",
            ]

        return [self.normalize_package_ndc(clean_ndc)]

    def query_fda(self, package_ndc: str):

        if not package_ndc:
            return None, None, None

        last_error = None
        last_url = None

        for candidate in self.build_ndc_candidates(package_ndc):
            search_query = (
                f'packaging.package_ndc:"{candidate}"'
            )

            encoded_query = quote(search_query)

            fda_url = (
                "https://api.fda.gov/drug/ndc.json"
                f"?search={encoded_query}"
            )

            logger.info(f"FDA query URL: {fda_url}")

            try:

                response = requests.get(
                    fda_url,
                    timeout=30
                )

                logger.info(
                    f"FDA response status: "
                    f"{response.status_code}"
                )

                if response.status_code == 200:

                    return response.json(), fda_url, candidate

                last_error = response.text
                last_url = fda_url

                logger.warning(
                    f"FDA API error: {response.text}"
                )

            except Exception as e:

                last_error = str(e)
                last_url = fda_url

                logger.error(f"FDA request failed: {e}")

        return {
            "error": last_error
        }, last_url, None

    # =========================================================
    # MAIN PIPELINE
    # =========================================================

    def process_barcode_base64(self, image_base64: str):

        pil_image = self.load_image_from_base64(
            image_base64
        )

        # -----------------------------------------------------
        # FAST BARCODE SCAN
        # -----------------------------------------------------

        barcode_data = self.scan_barcode(pil_image)

        ndc = barcode_data.get("ndc")

        # -----------------------------------------------------
        # FALLBACK TO LLM
        # -----------------------------------------------------

        llm_data = {}

        if not ndc:
            # Ensure LLM receives a JPEG, since some backends
            # do not accept HEIC/HEIF input.
            llm_image_base64 = self.encode_pil_image_to_jpeg_base64(
                pil_image
            )

            llm_data = self.fallback_llm_extraction(
                llm_image_base64
            )

            ndc = llm_data.get("ndc")

        # -----------------------------------------------------
        # NORMALIZE NDC
        # -----------------------------------------------------

        package_ndc = None

        if ndc:

            package_ndc = self.normalize_package_ndc(
                str(ndc)
            )

        logger.info(
            f"Normalized package NDC: {package_ndc}"
        )

        # -----------------------------------------------------
        # FDA LOOKUP
        # -----------------------------------------------------

        fda_data, fda_url, matched_package_ndc = self.query_fda(
            package_ndc
        )

        if matched_package_ndc:
            package_ndc = matched_package_ndc

        # -----------------------------------------------------
        # FINAL RESPONSE
        # -----------------------------------------------------

        final_data = {
            "ndc": ndc,
            "package_ndc": package_ndc,
            "gtin": (
                barcode_data.get("gtin")
                or llm_data.get("gtin")
            ),
            "exp": llm_data.get("exp"),
            "lot": llm_data.get("lot"),
            "sn": llm_data.get("sn")
        }

        logger.info("Processing complete.")

        return {
            "extracted_data": final_data,
            "fda_url": fda_url,
            "fda_data": fda_data
        }

    # =========================================================
    # IMAGE FILE INPUT
    # =========================================================

    def process_barcode_image(self, image_path: str):

        with open(image_path, "rb") as image_file:

            image_base64 = base64.b64encode(
                image_file.read()
            ).decode("utf-8")

        return self.process_barcode_base64(
            image_base64
        )


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":

    import os
    import sys

    processor = BarcodeProcessorService()

    base_dir = os.path.dirname(
        os.path.abspath(__file__)
    )

    default_image = os.path.join(
        base_dir,
        "image.png"
    )

    image_to_test = (
        sys.argv[1]
        if len(sys.argv) > 1
        else default_image
    )

    try:

        result = processor.process_barcode_image(
            image_to_test
        )

        print(json.dumps(result, indent=2))

    except Exception as e:

        print(f"Error processing image: {e}")