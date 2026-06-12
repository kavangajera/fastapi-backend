"""
invoice_extractor.py
────────────────────
Vision invoice extractor using any Ollama model (4B–27B safe).
Sends ONE page per LLM call so even 4B VL models fit in context.
Merges all pages into a single validated Invoice object.

Install:
    pip install pymupdf pillow langchain-ollama langchain-core pydantic loguru

Pull model:
    ollama pull qwen3-vl:4b       # fast, needs chunking (default)
    ollama pull gemma4:12b        # more accurate
    ollama pull gemma4:27b        # most accurate

Run:
    python invoice_extractor.py invoice.pdf
    python invoice_extractor.py invoice.pdf --model gemma4:12b
    python invoice_extractor.py invoice.pdf --model qwen3-vl:4b --out result.json
    python invoice_extractor.py invoice.pdf --debug
"""

from __future__ import annotations

import base64
import json
import os
import sys
from io import BytesIO
from pathlib import Path

import fitz
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from loguru import logger
from PIL import Image
from pydantic import BaseModel, Field, field_validator

# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────


class LineItem(BaseModel):
    line: str | None = None
    item_code: str | None = None
    ndc: str | None = None
    lot_number: str | None = None
    orig_order_qty: str | None = None
    order_qty: str | None = None
    invoiced_qty: str | None = None
    uom: str | None = None
    description: str | None = None
    size: str | None = None
    form: str | None = None
    unit_price: str | None = None
    extended_price: str | None = None
    awp: str | None = None
    note_code: str | None = None

    @field_validator(
        "line",
        "invoiced_qty",
        "orig_order_qty",
        "order_qty",
        mode="before",
    )
    @classmethod
    def coerce_to_str(cls, v):
        return str(v) if v is not None else None


class Summary(BaseModel):
    order_line_total: str | None = None
    fuel_surcharge: str | None = None
    sub_total: str | None = None
    tax: str | None = None
    grand_total: str | None = None
    total_due_by: str | None = None


class Invoice(BaseModel):
    seller_name: str | None = None
    seller_address: str | None = None
    seller_phone: str | None = None
    seller_dea: str | None = None
    seller_permit: str | None = None
    seller_fed_id: str | None = None

    invoice_number: str | None = None
    invoice_date: str | None = None
    order_number: str | None = None
    due_date: str | None = None
    terms_of_payment: str | None = None
    your_order_number: str | None = None

    customer_number: str | None = None
    customer_name: str | None = None
    customer_dea: str | None = None
    customer_state_reg: str | None = None

    bill_to_name: str | None = None
    bill_to_address: str | None = None
    ship_to_name: str | None = None
    ship_to_address: str | None = None

    line_items: list[LineItem] = Field(default_factory=list)
    summary: Summary = Field(default_factory=Summary)

    remit_to_name: str | None = None
    remit_to_address: str | None = None
    remit_to_phone: str | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Prompts  (kept short — 4B models lose attention on long system prompts)
# ─────────────────────────────────────────────────────────────────────────────

# Concise system prompt — important for small models
SYSTEM_PROMPT = """\
You are an invoice data extractor. Output ONLY valid JSON, no markdown, no explanation.

Rules:
- Extract every product row in the table — never skip one.
- seller = the company shipping/sending the invoice.
- customer = the pharmacy or buyer receiving the goods.
- item_code = vendor SKU (different from NDC).
- ndc = National Drug Code / UPC (digits, hyphens OK).
- lot_number = lot or batch number per line.
- size = pack size only (e.g. "100EA", "10ML").
- form = dosage form only (e.g. "TAB", "CAP", "SY").
- extended_price = unit_price × invoiced_qty.
- Absent fields → null. Never use "" or "N/A".
- Preserve numbers exactly as printed.
- line, invoiced_qty, orig_order_qty, order_qty → always strings.

Return this JSON shape (all fields optional except line_items array):
{
  "seller_name": null,
  "seller_address": null,
  "seller_phone": null,
  "seller_dea": null,
  "seller_permit": null,
  "seller_fed_id": null,
  "invoice_number": null,
  "invoice_date": null,
  "order_number": null,
  "due_date": null,
  "terms_of_payment": null,
  "your_order_number": null,
  "customer_number": null,
  "customer_name": null,
  "customer_dea": null,
  "customer_state_reg": null,
  "bill_to_name": null,
  "bill_to_address": null,
  "ship_to_name": null,
  "ship_to_address": null,
  "line_items": [
    {
      "line": null,
      "item_code": null,
      "ndc": null,
      "lot_number": null,
      "orig_order_qty": null,
      "order_qty": null,
      "invoiced_qty": null,
      "uom": null,
      "description": null,
      "size": null,
      "form": null,
      "unit_price": null,
      "extended_price": null,
      "awp": null,
      "note_code": null
    }
  ],
  "summary": {
    "order_line_total": null,
    "fuel_surcharge": null,
    "sub_total": null,
    "tax": null,
    "grand_total": null,
    "total_due_by": null
  },
  "remit_to_name": null,
  "remit_to_address": null,
  "remit_to_phone": null
}
"""

USER_PROMPT = (
    "Extract all invoice data from this page image. "
    "Return ONLY raw JSON — no markdown, no explanation, no preamble."
)


# ─────────────────────────────────────────────────────────────────────────────
# Provider settings (env-driven)
# ─────────────────────────────────────────────────────────────────────────────


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _active_provider_model(
    default_model: str,
    provider: str | None = None,
    openrouter_model: str | None = None,
) -> tuple[str, str]:
    resolved_provider = (provider or _env("PROVIDER", "ollama")).lower()
    if resolved_provider == "openrouter":
        model = openrouter_model or _env("OPENROUTER_MODEL", "qwen/qwen2.5-vl-72b")
        return "openrouter", (model or default_model)
    return "ollama", default_model


# ─────────────────────────────────────────────────────────────────────────────
# PDF → images
# ─────────────────────────────────────────────────────────────────────────────


def load_pdf_as_images(
    pdf_path: str,
    dpi_scale: float = 2.0,
    max_dim: int = 1024,
) -> list[Image.Image]:
    """
    Render every PDF page as a PIL image.
    Defaults are tuned for 4B models:
      dpi_scale=2.0, max_dim=1024  → ~250-400 KB base64 per page
    For larger models use dpi_scale=2.5, max_dim=2048.
    """
    logger.info(f"Opening PDF: {pdf_path}")
    doc = fitz.open(pdf_path)
    logger.info(f"Total pages: {len(doc)}")

    pages = []
    for idx, page in enumerate(doc):
        stored_angle = page.rotation
        logger.debug(f"Page {idx + 1}: stored rotation = {stored_angle}°")

        mat = fitz.Matrix(dpi_scale, dpi_scale)
        pix = page.get_pixmap(matrix=mat)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        logger.debug(f"Page {idx + 1}: rendered {img.size[0]}x{img.size[1]}px")

        # Correct stored PDF rotation
        rotation_map = {90: -90, 180: 180, 270: 90}
        if stored_angle in rotation_map:
            img = img.rotate(rotation_map[stored_angle], expand=True)
            logger.debug(f"Page {idx + 1}: corrected stored rotation {stored_angle}°")

        # Heuristic: landscape → portrait for portrait-format invoices
        w, h = img.size
        if w > h * 1.3:
            img = img.rotate(90, expand=True)
            logger.info(f"Page {idx + 1}: auto-rotated landscape→portrait")

        # Cap size for token budget
        max_side = max(img.size)
        if max_side > max_dim:
            scale = max_dim / max_side
            img = img.resize(
                (int(img.size[0] * scale), int(img.size[1] * scale)),
                Image.LANCZOS,
            )
            logger.debug(f"Page {idx + 1}: downscaled to {img.size[0]}x{img.size[1]}px")

        logger.info(f"Page {idx + 1}: final size {img.size[0]}x{img.size[1]}px")
        pages.append(img)

    return pages


def encode_image(img: Image.Image, quality: int = 82) -> str:
    """JPEG-encode a PIL image and return base64 string."""
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    encoded = base64.b64encode(buf.getvalue()).decode()
    logger.debug(f"Encoded image: {len(encoded):,} base64 chars")
    return encoded


# ─────────────────────────────────────────────────────────────────────────────
# Single-page LLM call
# ─────────────────────────────────────────────────────────────────────────────


def call_llm_single_page(
    page: Image.Image,
    page_num: int,
    total_pages: int,
    model: str,
    ollama_url: str,
    temperature: float,
    provider: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_base_url: str | None = None,
    openrouter_model: str | None = None,
) -> dict:
    """
    Send ONE page image to the model and return a parsed dict.
    Soft-fails (returns {}) on empty response or bad JSON
    so one bad page doesn't crash the whole run.
    """
    provider, model_used = _active_provider_model(
        model,
        provider=provider,
        openrouter_model=openrouter_model,
    )
    logger.info(
        f"Page {page_num}/{total_pages} → {provider}:{model_used} "
        f"(image: {page.size[0]}x{page.size[1]}px)"
    )

    if provider == "openrouter":
        api_key = openrouter_api_key or _env("OPENROUTER_API_KEY", "")
        base_url = openrouter_base_url or _env(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        )
        if not api_key:
            logger.error("OpenRouter selected but OPENROUTER_API_KEY is missing")
            return {}
        llm = ChatOpenAI(
            model=openrouter_model or model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=4096,
            default_headers={
                "HTTP-Referer": "http://localhost",
                "X-Title": "fastapi-backend-invoice-extractor",
            },
        )
    else:
        llm = ChatOllama(
            model=model,
            base_url=ollama_url,
            temperature=temperature,
            format="json",  # enforce JSON mode — no markdown fences
            num_predict=4096,  # plenty for one page; keeps latency down
        )

    content = [
        {
            "type": "text",
            "text": f"=== PAGE {page_num} OF {total_pages} ===",
        },
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{encode_image(page)}"},
        },
        {"type": "text", "text": USER_PROMPT},
    ]

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=content),
    ]

    try:
        response = llm.invoke(messages)
    except Exception as exc:
        logger.error(f"Page {page_num}: LLM call failed — {exc}")
        return {}

    raw = response.content.strip()
    logger.debug(f"Page {page_num}: response length = {len(raw):,} chars")
    logger.debug(f"Page {page_num}: first 400 chars:\n{raw[:400]}")

    # Empty response — model gave up (context overload, etc.)
    if not raw:
        logger.warning(
            f"Page {page_num}: empty response from model. Try --max-dim 800 or a larger model."
        )
        return {}

    # Strip accidental markdown fences (format=json should prevent but just in case)
    if raw.startswith("```"):
        raw = "\n".join(
            line for line in raw.splitlines() if not line.strip().startswith("```")
        ).strip()
        logger.debug(f"Page {page_num}: stripped markdown fences")

    try:
        parsed = json.loads(raw)
        items = parsed.get("line_items", [])
        logger.info(f"Page {page_num}: parsed OK — {len(items)} line item(s)")
        return parsed
    except json.JSONDecodeError as exc:
        logger.error(f"Page {page_num}: JSON decode failed — {exc}")
        logger.error(f"Page {page_num}: raw content:\n{raw[:600]}")
        return {}


# ─────────────────────────────────────────────────────────────────────────────
# Merge per-page results → single Invoice dict
# ─────────────────────────────────────────────────────────────────────────────

HEADER_FIELDS = [
    "seller_name",
    "seller_address",
    "seller_phone",
    "seller_dea",
    "seller_permit",
    "seller_fed_id",
    "invoice_number",
    "invoice_date",
    "order_number",
    "due_date",
    "terms_of_payment",
    "your_order_number",
    "customer_number",
    "customer_name",
    "customer_dea",
    "customer_state_reg",
    "bill_to_name",
    "bill_to_address",
    "ship_to_name",
    "ship_to_address",
    "remit_to_name",
    "remit_to_address",
    "remit_to_phone",
]


def merge_page_results(pages_data: list[dict]) -> dict:
    """
    Merge per-page dicts into one Invoice-shaped dict.

    Strategy:
      - Header fields  : first non-null value wins (page 1 usually has header)
      - line_items     : concatenated in page order
      - summary        : last non-null wins (totals appear on the last page)
    """
    merged: dict = {}
    all_line_items: list = []

    for page_num, page_data in enumerate(pages_data, start=1):
        if not page_data:
            logger.warning(f"Page {page_num}: empty result — skipping in merge")
            continue

        # Header fields: first non-null wins
        for field in HEADER_FIELDS:
            if merged.get(field) is None and page_data.get(field) is not None:
                merged[field] = page_data[field]
                logger.debug(f"Merged header '{field}' from page {page_num}")

        # Line items: accumulate
        items = page_data.get("line_items", [])
        if isinstance(items, list) and items:
            logger.debug(f"Page {page_num}: adding {len(items)} line item(s) to merge")
            all_line_items.extend(items)

        # Summary: last non-null wins
        summary = page_data.get("summary")
        if isinstance(summary, dict) and any(v is not None for v in summary.values()):
            merged["summary"] = summary
            logger.debug(f"Summary updated from page {page_num}")

    merged["line_items"] = all_line_items
    if "summary" not in merged:
        merged["summary"] = {}

    logger.info(
        f"Merge complete: {len(all_line_items)} total line item(s) from {len(pages_data)} page(s)"
    )
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Orchestrator: iterate pages, merge, validate
# ─────────────────────────────────────────────────────────────────────────────


def call_llm(
    pages: list[Image.Image],
    model: str,
    ollama_url: str,
    temperature: float,
    provider: str | None = None,
    openrouter_api_key: str | None = None,
    openrouter_base_url: str | None = None,
    openrouter_model: str | None = None,
) -> dict:
    """
    Send each page individually and merge results.
    Safe for any model size — no context overload.
    """
    provider, model_used = _active_provider_model(
        model,
        provider=provider,
        openrouter_model=openrouter_model,
    )
    logger.info(
        f"Chunked extraction: {len(pages)} page(s) × 1 image/call → {provider}:{model_used}"
    )

    pages_data: list[dict] = []
    for i, page in enumerate(pages, start=1):
        result = call_llm_single_page(
            page=page,
            page_num=i,
            total_pages=len(pages),
            model=model,
            ollama_url=ollama_url,
            temperature=temperature,
            provider=provider,
            openrouter_api_key=openrouter_api_key,
            openrouter_base_url=openrouter_base_url,
            openrouter_model=openrouter_model,
        )
        pages_data.append(result)

    return merge_page_results(pages_data)


# ─────────────────────────────────────────────────────────────────────────────
# Logging helper
# ─────────────────────────────────────────────────────────────────────────────


def log_invoice_summary(invoice: Invoice) -> None:
    sep = "═" * 80
    logger.info(sep)
    logger.info("  PARSED INVOICE SUMMARY")
    logger.info(sep)
    logger.info(f"  Seller   : {invoice.seller_name}")
    logger.info(f"  Address  : {invoice.seller_address}")
    logger.info(f"  Phone    : {invoice.seller_phone}")
    logger.info(f"  DEA      : {invoice.seller_dea}")
    logger.info(f"  Permit   : {invoice.seller_permit}")
    logger.info("─" * 80)
    logger.info(f"  Invoice# : {invoice.invoice_number}")
    logger.info(f"  Date     : {invoice.invoice_date}")
    logger.info(f"  Order#   : {invoice.order_number}")
    logger.info(f"  Terms    : {invoice.terms_of_payment}")
    logger.info(f"  Due Date : {invoice.due_date}")
    logger.info("─" * 80)
    logger.info(f"  Customer : {invoice.customer_name}")
    logger.info(f"  Cust DEA : {invoice.customer_dea}")
    logger.info(f"  State Reg: {invoice.customer_state_reg}")
    logger.info(f"  Bill To  : {invoice.bill_to_name} | {invoice.bill_to_address}")
    logger.info(f"  Ship To  : {invoice.ship_to_name} | {invoice.ship_to_address}")
    logger.info("─" * 80)
    logger.info(f"  Line Items: {len(invoice.line_items)}")
    logger.info(
        f"  {'#':>4}  {'ITEM':12}  {'NDC':17}  {'QTY':>5}  {'UNIT':>9}  {'EXT':>9}  DESCRIPTION"
    )
    logger.info("  " + "─" * 76)
    for item in invoice.line_items:
        logger.info(
            f"  {item.line or '?':>4}  "
            f"{item.item_code or '—':12}  "
            f"{item.ndc or '—':17}  "
            f"{item.invoiced_qty or '?':>5}  "
            f"{item.unit_price or '—':>9}  "
            f"{item.extended_price or '—':>9}  "
            f"{(item.description or '—')[:55]}"
        )
    logger.info("─" * 80)
    s = invoice.summary
    logger.info(f"  Order Line Total : {s.order_line_total}")
    logger.info(f"  Fuel Surcharge   : {s.fuel_surcharge}")
    logger.info(f"  Sub Total        : {s.sub_total}")
    logger.info(f"  Tax              : {s.tax}")
    logger.info(f"  Grand Total      : {s.grand_total}")
    logger.info(f"  Total Due By     : {s.total_due_by}")
    logger.info("─" * 80)
    logger.info(f"  Remit To : {invoice.remit_to_name} | {invoice.remit_to_address}")
    logger.info(sep)


# ─────────────────────────────────────────────────────────────────────────────
# Public parser class
# ─────────────────────────────────────────────────────────────────────────────


class InvoiceParser:
    def __init__(
        self,
        model: str = "qwen3-vl:4b",
        ollama_url: str = "http://127.0.0.1:11434",
        temperature: float = 0.0,
        dpi_scale: float = 2.0,
        max_dim: int = 1024,
        provider: str | None = None,
        openrouter_api_key: str | None = None,
        openrouter_base_url: str | None = None,
        openrouter_model: str | None = None,
    ):
        self.model = model
        self.ollama_url = ollama_url
        self.temperature = temperature
        self.dpi_scale = dpi_scale
        self.max_dim = max_dim
        self.provider = provider
        self.openrouter_api_key = openrouter_api_key
        self.openrouter_base_url = openrouter_base_url
        self.openrouter_model = openrouter_model

        provider, model_used = _active_provider_model(
            model,
            provider=provider,
            openrouter_model=openrouter_model,
        )
        provider_details = (
            f"provider={provider} | model={model_used}"
            if provider == "openrouter"
            else f"provider={provider} | model={model_used} | ollama_url={ollama_url}"
        )
        logger.info(
            f"InvoiceParser ready | {provider_details} | "
            f"dpi={dpi_scale} | max_dim={max_dim} | chunked=True (1 page/call)"
        )

    def parse(self, pdf_path: str) -> Invoice:
        logger.info(f"Starting extraction: {pdf_path}")

        pages = load_pdf_as_images(
            pdf_path,
            dpi_scale=self.dpi_scale,
            max_dim=self.max_dim,
        )

        raw_dict = call_llm(
            pages,
            model=self.model,
            ollama_url=self.ollama_url,
            temperature=self.temperature,
            provider=self.provider,
            openrouter_api_key=self.openrouter_api_key,
            openrouter_base_url=self.openrouter_base_url,
            openrouter_model=self.openrouter_model,
        )

        logger.info("Validating against schema...")
        try:
            invoice = Invoice(**raw_dict)
            logger.info(f"Schema validation passed — {len(invoice.line_items)} line item(s)")
        except Exception as exc:
            logger.error(f"Schema validation failed: {exc}")
            raise

        log_invoice_summary(invoice)
        logger.info("Extraction complete.")
        return invoice


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description=(
            "Invoice extractor — chunked vision via Ollama.\n"
            "Sends 1 page per LLM call so 4B models work fine."
        )
    )
    ap.add_argument("pdf", help="Path to invoice PDF")
    ap.add_argument(
        "--model",
        default="qwen3-vl:4b",
        help="Ollama model tag (default: qwen3-vl:4b)",
    )
    ap.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434",
        help="Ollama server URL (default: http://127.0.0.1:11434)",
    )
    ap.add_argument(
        "--temperature",
        type=float,
        default=0.0,
        help="LLM temperature (default: 0.0)",
    )
    ap.add_argument(
        "--dpi",
        type=float,
        default=2.0,
        help="PDF render DPI scale — 4B: 2.0, 12B+: 2.5 (default: 2.0)",
    )
    ap.add_argument(
        "--max-dim",
        type=int,
        default=1024,
        help="Max image dimension px — 4B: 1024, 12B+: 2048 (default: 1024)",
    )
    ap.add_argument(
        "--out",
        default=None,
        help="Save JSON output to this file path",
    )
    ap.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG log level",
    )
    args = ap.parse_args()

    logger.remove()
    logger.add(
        sys.stderr,
        level="DEBUG" if args.debug else "INFO",
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level:8}</level> | "
            "<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
    )

    parser = InvoiceParser(
        model=args.model,
        ollama_url=args.ollama_url,
        temperature=args.temperature,
        dpi_scale=args.dpi,
        max_dim=args.max_dim,
    )

    result = parser.parse(args.pdf)
    output = result.model_dump_json(indent=2)

    print(output)

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        logger.info(f"JSON saved to: {args.out}")
