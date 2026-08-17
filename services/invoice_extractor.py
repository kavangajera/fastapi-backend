"""Strict Gemini vision invoice extraction with one forced tool call per page."""

from __future__ import annotations

import base64
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from time import perf_counter
from typing import Any

import fitz
from loguru import logger
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from core.config import settings
from services.extraction_errors import NoExtractableDataError

TOOL_NAME = "extract_invoice_page"
SYSTEM_PROMPT = """Extract exact visible invoice data from one page and call the tool once.
Copy strings exactly; never infer, calculate, repair, or copy values between fields.
Omit absent fields. Extract every product row and never merge rows. Seller sends the invoice;
customer receives it. item_code is the vendor SKU; ndc is NDC/UPC. size is pack size and form
is dosage form. Ignore repeated headers. Header values use the first page where visible;
summary values belong to the page where printed. Caution: a row may print description, quantity,
and price crowded together on one line or in one visually merged column; still split them into
their correct separate fields (description, order_qty/invoiced_qty, unit_price/extended_price)
rather than leaving them concatenated or copying the whole crowded text into a single field.
Call the tool exactly once for every page, no matter its content or layout — never respond
without calling it. If a page has no product rows at all (a cover page, signature page, blank
page, or a totals-only page), still call the tool and pass an empty line_items list rather than
refusing or describing the page in plain text."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LineItem(StrictModel):
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


class Summary(StrictModel):
    order_line_total: str | None = None
    fuel_surcharge: str | None = None
    sub_total: str | None = None
    tax: str | None = None
    grand_total: str | None = None
    total_due_by: str | None = None


class Invoice(StrictModel):
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


def _schema() -> dict[str, Any]:
    schema = Invoice.model_json_schema()
    definitions = schema.get("$defs", {})

    def expand(node: Any) -> Any:
        if isinstance(node, list):
            return [expand(value) for value in node]
        if not isinstance(node, dict):
            return node
        reference = node.get("$ref")
        if isinstance(reference, str) and reference.startswith("#/$defs/"):
            resolved = copy.deepcopy(definitions[reference.removeprefix("#/$defs/")])
            resolved.update({key: value for key, value in node.items() if key != "$ref"})
            return expand(resolved)
        return {
            key: expand(value)
            for key, value in node.items()
            if key not in {"$defs", "default", "title"}
        }

    return expand(schema)


def _tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Extract sparse visible invoice fields from one page.",
            # See dispense_gemini_extractor.py::extraction_tool — grammar-
            # constrained decoding is what actually prevents malformed
            # function-call JSON. Compatible here for the same reason:
            # extra="forbid" on every model (-> additionalProperties: false)
            # and every field optional/nullable.
            "strict": True,
            "parameters": _schema(),
        },
    }


def _render(pdf_path: str) -> list[str]:
    document = fitz.open(pdf_path)
    images: list[str] = []
    try:
        for page in document:
            pixmap = page.get_pixmap(dpi=settings.DOCUMENT_LLM_RENDER_DPI, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
            images.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
    finally:
        document.close()
    return images


_NUDGE = (
    "You must call the extract_invoice_page tool exactly once for this page. If the page "
    "has no product rows (a cover, signature, blank, or totals-only page), call the tool "
    "anyway with an empty line_items list — do not respond without calling the tool."
)


def _call_extraction_tool(
    client: OpenAI, image: str, page_number: int, page_count: int, *, nudge: bool = False
):
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Extract invoice page {page_number}/{page_count}."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image}"}},
            ],
        },
    ]
    if nudge:
        messages.append({"role": "user", "content": _NUDGE})
    return client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        temperature=0,
        max_tokens=settings.DOCUMENT_LLM_MAX_OUTPUT_TOKENS,
        messages=messages,
        tools=[_tool()],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        extra_body={
            "provider": {
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
            },
            # See dispense_gemini_extractor.py — thinking tokens otherwise
            # draw from the same max_tokens budget as the function-call
            # output and can truncate it into MALFORMED_FUNCTION_CALL on
            # dense pages.
            "reasoning": {"enabled": False},
        },
    )


_MAX_PAGE_ATTEMPTS = 4


def _extract_page(image: str, page_number: int, page_count: int) -> tuple[int, Invoice, dict]:
    """Extract one page. A page with nothing to extract (cover, signature,
    blank, totals-only) is not a failure — every `Invoice` field is optional.
    Gemini's function-call generation is not perfectly reliable on dense
    pages even with reasoning disabled and a generous token budget, so
    retry a few times before giving up. If it still never returns a valid
    tool call, that one page is treated as empty rather than failing the
    whole multi-page document; whether the document as a whole is an
    invoice is judged once, after all pages are merged (see
    `InvoiceParser.parse`)."""
    client = OpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=settings.DOCUMENT_LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )
    started = perf_counter()

    response = None
    calls: list = []
    for attempt in range(1, _MAX_PAGE_ATTEMPTS + 1):
        try:
            response = _call_extraction_tool(
                client, image, page_number, page_count, nudge=attempt > 1
            )
            # Under heavy concurrent load a provider can occasionally hand
            # back a degraded/error-shaped 200 response (e.g. `choices`
            # missing or None) instead of a clean HTTP error. Treat that
            # the same as "no tool call" — retry.
            choices = getattr(response, "choices", None) or []
            calls = choices[0].message.tool_calls or [] if choices else []
        except Exception as exc:
            # Also under heavy load, the call can fail before we even get
            # a parsed response — timeouts, connection resets, or a
            # truncated HTTP body the SDK can't JSON-decode. None of that
            # is this page's fault; retry rather than losing the whole
            # multi-page document to one attempt's transport hiccup.
            logger.warning(
                "Invoice page {p} attempt {a}/{n} raised {error} — retrying",
                p=page_number,
                a=attempt,
                n=_MAX_PAGE_ATTEMPTS,
                error=f"{type(exc).__name__}: {exc}",
            )
            response = None
            calls = []
            continue
        if len(calls) == 1 and calls[0].function.name == TOOL_NAME:
            break
        logger.warning(
            "Invoice page {p} attempt {a}/{n} did not return a tool call",
            p=page_number,
            a=attempt,
            n=_MAX_PAGE_ATTEMPTS,
        )

    page_failed = False
    if len(calls) != 1 or calls[0].function.name != TOOL_NAME:
        logger.warning(
            "Invoice page {p} never returned a tool call after {n} attempts — treating as an empty page",
            p=page_number,
            n=_MAX_PAGE_ATTEMPTS,
        )
        # Distinct from a legitimately empty page — see `InvoiceParser.parse`.
        page_failed = True
        invoice = Invoice()
    else:
        invoice = Invoice.model_validate_json(calls[0].function.arguments)

    usage = getattr(response, "usage", None)
    usage_extra = getattr(usage, "model_extra", None) or {}
    return (
        page_number,
        invoice,
        {
            "seconds": perf_counter() - started,
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "cost": getattr(usage, "cost", None) or usage_extra.get("cost"),
            "failed": page_failed,
        },
    )


def _merge(pages: list[Invoice]) -> Invoice:
    merged: dict[str, Any] = {"line_items": [], "summary": {}}
    for page in pages:
        payload = page.model_dump(exclude_none=True)
        merged["line_items"].extend(payload.pop("line_items", []))
        summary = payload.pop("summary", {})
        if summary:
            merged["summary"].update(summary)
        for key, value in payload.items():
            merged.setdefault(key, value)
    return Invoice.model_validate(merged)


class InvoiceParser:
    """Backward-compatible public parser used by the invoice service."""

    def __init__(self, **_: Any) -> None:
        pass

    def parse(self, pdf_path: str) -> Invoice:
        started = perf_counter()
        images = _render(pdf_path)
        results: dict[int, Invoice] = {}
        metrics: list[dict] = []
        with ThreadPoolExecutor(max_workers=settings.DOCUMENT_LLM_MAX_CONCURRENCY) as executor:
            futures = [
                executor.submit(_extract_page, image, index, len(images))
                for index, image in enumerate(images, start=1)
            ]
            for future in as_completed(futures):
                page_number, invoice, page_metrics = future.result()
                results[page_number] = invoice
                metrics.append(page_metrics)
        logger.info(
            "Gemini invoice extraction complete: pages={pages} seconds={seconds:.2f} "
            "prompt_tokens={prompt} completion_tokens={completion} cost={cost}",
            pages=len(images),
            seconds=perf_counter() - started,
            prompt=sum(item["prompt_tokens"] or 0 for item in metrics),
            completion=sum(item["completion_tokens"] or 0 for item in metrics),
            cost=sum(float(item["cost"] or 0) for item in metrics),
        )
        invoice = _merge([results[index] for index in sorted(results)])
        if _invoice_has_data(invoice):
            return invoice

        # See `dispense_gemini_extractor.process_pdf` — when every page
        # failed outright the cause is systemic, and reporting it as "not an
        # invoice" would permanently fail a valid document with no retry.
        failed_pages = sum(1 for item in metrics if item.get("failed"))
        if failed_pages:
            raise RuntimeError(
                f"Extraction produced no data and {failed_pages}/{len(images)} page(s) "
                f"never returned a valid response from the model. This looks like a "
                f"provider/transport problem (outage, rate limit, or exhausted credit) "
                f"rather than a problem with the document — retrying."
            )

        raise NoExtractableDataError(
            f"No invoice/line-item data could be extracted from any of the "
            f"{len(images)} page(s) in this document — it does not appear "
            f"to be an invoice."
        )


def _invoice_has_data(invoice: Invoice) -> bool:
    if invoice.line_items:
        return True
    header = invoice.model_dump(exclude_none=True, exclude={"line_items", "summary"})
    if header:
        return True
    return bool(invoice.summary.model_dump(exclude_none=True))
