from __future__ import annotations

import base64
import json
import os
from io import BytesIO
from typing import Any

import fitz
from langchain_core.messages import HumanMessage, SystemMessage
from core.config import settings
from langchain_openai import ChatOpenAI
from loguru import logger
from PIL import Image
from pydantic import BaseModel, Field

# ─────────────────────────────────────────────────────────────────────────────
# Schema (Matches schemas.save_dispense exactly)
# ─────────────────────────────────────────────────────────────────────────────

class DispensePharmacyMeta(BaseModel):
    pharmacy_name: str | None = None
    address: str | None = None
    phone: str | None = None
    fax: str | None = None
    report_date: str | None = None
    report_from_date: str | None = None
    report_to_date: str | None = None

class DispenseGrandTotal(BaseModel):
    total_rx_count: str | int | None = None
    total_price: str | None = None
    total_cost: str | None = None

class DispenseLineInput(BaseModel):
    qty_disp: str | None = None
    qty_ord: str | None = None
    days_supply: str | int | None = None
    date_filled: str | None = None
    rx_no: str | None = None
    ref: str | None = None
    pat_name: str | None = None
    pat_addr: str | None = None
    pat_phone: str | None = None
    pres_name: str | None = None
    pres_addr: str | None = None
    pres_phone: str | None = None
    price: str | None = None
    ins_paid: str | None = None
    ins_code: str | None = None
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None

class MedicineTotalsInput(BaseModel):
    packs: str | None = None
    total_rx_count: str | int | None = None
    total_ins_paid: str | None = None
    total_price: str | None = None
    total_cost: str | None = None

class MedicineInput(BaseModel):
    drug_name: str
    ndc: str
    inventory_bucket: str | None = None
    lot_no_exp_date: str | None = None
    totals: MedicineTotalsInput | None = Field(default_factory=MedicineTotalsInput)
    dispenses: list[DispenseLineInput] = Field(default_factory=list)

class DispenseReport(BaseModel):
    pharmacy: DispensePharmacyMeta = Field(default_factory=DispensePharmacyMeta)
    medicines: list[MedicineInput] = Field(default_factory=list)
    grand_total: DispenseGrandTotal = Field(default_factory=DispenseGrandTotal)

# ─────────────────────────────────────────────────────────────────────────────
# Prompts
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a highly accurate data extraction system for Pharmacy Drug Dispensed Reports.
Output ONLY valid JSON, no markdown formatting, no explanations.

Map the extracted data to this exact JSON schema:
{
  "pharmacy": {
    "pharmacy_name": null, "address": null, "phone": null, "fax": null,
    "report_date": null, "report_from_date": null, "report_to_date": null
  },
  "medicines": [
    {
      "drug_name": null,
      "ndc": null,
      "inventory_bucket": null,
      "lot_no_exp_date": null,
      "totals": {
        "packs": null, "total_rx_count": null, "total_ins_paid": null, "total_price": null, "total_cost": null
      },
      "dispenses": [
        {
          "qty_disp": null, "qty_ord": null, "days_supply": null, "date_filled": null,
          "rx_no": null, "ref": null,
          "pat_name": null, "pat_addr": null, "pat_phone": null,
          "pres_name": null, "pres_addr": null, "pres_phone": null,
          "price": null, "ins_paid": null, "ins_code": null,
          "inventory_bucket": null, "lot_no_exp_date": null
        }
      ]
    }
  ],
  "grand_total": {
    "total_rx_count": null, "total_price": null, "total_cost": null
  }
}

Definitions & Rules:
- Drug Name: Medication, Item Name, Ordered Drug.
- NDC: National Drug Code (11 digits, extract numbers only).
- RX Number (rx_no): Prescription Number, Script No.
- Date Filled: Dispense Date, Processing Date.
- Days Supply: Day Supply, Supply Days.
- Qty Disp: Quantity Filled, Dispensed Amount.
- Qty Ord: Quantity Prescribed, Original Qty.
- Ref: Refills Left, Remaining Refills.
- Ins Code: BIN, Plan Code, Carrier Code, Processor Code (e.g. MCD, AD1).
- Ins Paid: Third Party Paid, Amount Covered.
- Price: Total Charge, Gross Amount.
- Inventory Bucket: Stock Bucket, Inv, Shelf (e.g. General, C, S).
- Lot No/Exp Date: Batch Number, Expiration.
- Patient/Prescriber fields: Names, Addresses, Phones.
- Totals: Match totals per drug ("Total For", "Total Ins Paid", etc.).
- Grand Total: Overall report totals at the very end of the document. Do NOT confuse page numbers (e.g., "Page 7") with the total_rx_count.
- CRITICAL: Extract EVERY SINGLE dispense row perfectly. DO NOT drop, skip, or summarize rows, even if there are hundreds of them.
- CRITICAL: Do NOT merge dispense rows together even if they share the same Drug Name and NDC. Keep every single dispense record separate in the `dispenses` array.
- DO NOT invent data. If a field is missing, output null.
- Strip "$" and "," from money fields.
- Strip formatting from phones to leave just digits if possible, or leave as printed.
- Group all dispenses under their respective medicine (Drug Name & NDC).
"""


# ─────────────────────────────────────────────────────────────────────────────
# Image Encoding
# ─────────────────────────────────────────────────────────────────────────────

def encode_image(img: Image.Image, quality: int = 82) -> str:
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return base64.b64encode(buf.getvalue()).decode()

def load_pdf_as_images(pdf_bytes: bytes, dpi_scale: float = 2.0, max_dim: int = 1536) -> list[Image.Image]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    for _idx, page in enumerate(doc):
        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        
        max_side = max(img.size)
        if max_side > max_dim:
            scale = max_dim / max_side
            img = img.resize((int(img.size[0] * scale), int(img.size[1] * scale)), Image.LANCZOS)
            
        pages.append(img)
    return pages

# ─────────────────────────────────────────────────────────────────────────────
# LLM Calls
# ─────────────────────────────────────────────────────────────────────────────

def call_llm(content_payload: list, chunk_label: str | int, total_pages: int) -> dict:
    model = getattr(settings, "OPENROUTER_MODEL", "qwen/qwen3-vl-8b-instruct")
    logger.info(f"Chunk {chunk_label}/{total_pages} -> openrouter:{model}")

    api_key = getattr(settings, "OPENROUTER_API_KEY", "")
    base_url = getattr(settings, "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.0,
        max_tokens=8192,
        default_headers={"HTTP-Referer": "http://localhost", "X-Title": "fastapi-backend-dispense"},
    )

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=content_payload)
    ]

    try:
        response = llm.bind(response_format={"type": "json_object"}).invoke(messages)
        raw = response.content.strip()
        if raw.startswith("```"):
            raw = "\n".join(line for line in raw.splitlines() if not line.strip().startswith("```")).strip()
        return json.loads(raw)
    except Exception as exc:
        logger.error(f"Chunk {chunk_label} LLM call failed: {exc}")
        return {}

def merge_chunks(chunks: list[dict]) -> dict:
    merged = {
        "pharmacy": {},
        "medicines": [],
        "grand_total": {}
    }
    
    meds_dict = {}

    for c in chunks:
        if not c:
            continue
        
        # Merge pharmacy header (first wins)
        pharmacy = c.get("pharmacy", {})
        for k, v in pharmacy.items():
            if v is not None and merged["pharmacy"].get(k) is None:
                merged["pharmacy"][k] = v
                
        # Merge grand total (last wins)
        gt = c.get("grand_total", {})
        for k, v in gt.items():
            if v is not None:
                merged["grand_total"][k] = v

        # Merge medicines and dispenses
        for med in c.get("medicines", []):
            med_key = (med.get("drug_name"), med.get("ndc"))
            if not med_key[0] or not med_key[1]:
                continue
                
            # Ensure rx_no is a string for validation
            for d in med.get("dispenses", []):
                if d.get("rx_no") is not None:
                    d["rx_no"] = str(d["rx_no"])
                    
            if med_key not in meds_dict:
                meds_dict[med_key] = med
                if not meds_dict[med_key].get("totals"):
                    meds_dict[med_key]["totals"] = {}
                if not meds_dict[med_key].get("dispenses"):
                    meds_dict[med_key]["dispenses"] = []
            else:
                # Merge totals (last wins)
                t = med.get("totals", {})
                for k, v in t.items():
                    if v is not None:
                        meds_dict[med_key]["totals"][k] = v
                        
                # Append dispenses
                meds_dict[med_key]["dispenses"].extend(med.get("dispenses", []))

    merged["medicines"] = list(meds_dict.values())
    return merged

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def process_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    pages = load_pdf_as_images(pdf_bytes)
    chunks = []
    
    # We batch pages to speed up extraction, but we limit to 2 pages per API call
    # because the *output* JSON size (including reasoning tokens) can quickly
    # exceed the max_tokens limit on dense reports.
    PAGE_CHUNK_SIZE = 2
    
    for chunk_idx in range(0, len(pages), PAGE_CHUNK_SIZE):
        page_batch = pages[chunk_idx:chunk_idx + PAGE_CHUNK_SIZE]
        
        content = []
        for i, page in enumerate(page_batch):
            actual_page_num = chunk_idx + i + 1
            content.extend([
                {"type": "text", "text": f"=== PAGE {actual_page_num} OF {len(pages)} ==="},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{encode_image(page)}"}},
            ])
            
        content.append({"type": "text", "text": "Extract dispense data from these pages. Return ONLY JSON."})
        
        result = call_llm(content, f"{chunk_idx+1}-{chunk_idx+len(page_batch)}", len(pages))
        chunks.append(result)
        
    return merge_chunks(chunks)

def process_text_doc(text_lines: list[str]) -> dict[str, Any]:
    # Split text into chunks of roughly 100 lines (~1000 tokens)
    CHUNK_SIZE = 100
    text_chunks = [lines for i in range(0, len(text_lines), CHUNK_SIZE) if (lines := text_lines[i:i+CHUNK_SIZE])]
    
    chunks = []
    for i, chunk_lines in enumerate(text_chunks, 1):
        content = [
            {"type": "text", "text": f"=== CHUNK {i} OF {len(text_chunks)} ==="},
            {"type": "text", "text": "Extract dispense data from this text. The text is extracted row-by-row from a table. Return ONLY JSON.\n\nTEXT:\n" + "\n".join(chunk_lines)},
        ]
        result = call_llm(content, i, len(text_chunks))
        chunks.append(result)
        
    return merge_chunks(chunks)
