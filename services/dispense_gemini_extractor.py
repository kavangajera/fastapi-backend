"""Gemini vision extraction for dispense reports that do not match the legacy layout."""

from __future__ import annotations

import base64
import copy
import json
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

TOOL_NAME = "extract_dispense_page"
SYSTEM_PROMPT = """Extract exact visible pharmacy data from one page; call the tool once.
The image controls layout. Copy strings exactly; never infer, calculate, repair, or merge.
Omit absent fields. Ignore repeated headers and examples.
Summary (Total For/Packs/TotalRxCount/no patient or RX): d=[]; Qty Disp->t.qd,
Packs->t.pk, TotalRxCount->t.rx. Detail: every row under its drug+NDC;
stacked Qty Disp/Qty Ord->qd/qo. Price->pr, cash/retail->cp, total->tp;
Ref#/Ref->ref, explicit Reference Number->rno. Report FROM/To->rf/rt; Date:->rd.
x=true only for a visibly clipped or continuing row. Never create fake dispense rows.
Keys: root p=page, ph=pharmacy, gt=grand total, m=medicines. Pharmacy n=name,
a=address, ph=phone, fx=fax, rd=report date, rf/from, rt/to. Medicine n=drug,
ndc=NDC, ib=inventory, lot=lot, exp=expiration, pack=pack size, mfr=manufacturer,
gen=generic, str=strength, daw=DAW, sch=schedule, t=totals, d=dispenses.
Totals pk=packs, qd=quantity dispensed, rx=RX count, ins=insurance paid,
price=price, cost=cost. Dispense x=partial, rx=RX, rno=reference, qo/qd=quantities,
ds=days supply, df/dw/sold/wc=dates, ref=refills, pn/pa/pp=patient fields,
pdob/pg/pid=DOB/gender/ID, ic/ip/pc=insurance/copay, pr/cp/tp=prices,
dn/da/dp=prescriber fields, dea/npi=prescriber identifiers."""


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class CompactPharmacy(ToolModel):
    pharmacy_name: str | None = Field(None, alias="n")
    address: str | None = Field(None, alias="a")
    phone: str | None = Field(None, alias="ph")
    fax: str | None = Field(None, alias="fx")
    report_date: str | None = Field(None, alias="rd")
    report_from_date: str | None = Field(None, alias="rf")
    report_to_date: str | None = Field(None, alias="rt")


class CompactTotals(ToolModel):
    packs: str | None = Field(None, alias="pk")
    total_quantity_dispensed: str | None = Field(None, alias="qd")
    total_rx_count: str | None = Field(None, alias="rx")
    total_ins_paid: str | None = Field(None, alias="ins")
    total_price: str | None = Field(None, alias="price")
    total_cost: str | None = Field(None, alias="cost")


class CompactGrandTotal(ToolModel):
    total_rx_count: str | None = Field(None, alias="rx")
    total_ins_paid: str | None = Field(None, alias="ins")
    total_price: str | None = Field(None, alias="price")
    total_cost: str | None = Field(None, alias="cost")


class CompactDispense(ToolModel):
    is_partial: bool = Field(False, alias="x")
    rx_no: str | None = Field(None, alias="rx")
    reference_number: str | None = Field(None, alias="rno")
    qty_ord: str | None = Field(None, alias="qo")
    qty_disp: str | None = Field(None, alias="qd")
    days_supply: str | None = Field(None, alias="ds")
    date_filled: str | None = Field(None, alias="df")
    date_written: str | None = Field(None, alias="dw")
    date_sold: str | None = Field(None, alias="sold")
    will_call_date: str | None = Field(None, alias="wc")
    ref: str | None = None
    pat_name: str | None = Field(None, alias="pn")
    pat_addr: str | None = Field(None, alias="pa")
    pat_phone: str | None = Field(None, alias="pp")
    patient_dob: str | None = Field(None, alias="pdob")
    patient_gender: str | None = Field(None, alias="pg")
    patient_id: str | None = Field(None, alias="pid")
    ins_code: str | None = Field(None, alias="ic")
    ins_paid: str | None = Field(None, alias="ip")
    patient_copay: str | None = Field(None, alias="pc")
    price: str | None = Field(None, alias="pr")
    cash_price: str | None = Field(None, alias="cp")
    total_price: str | None = Field(None, alias="tp")
    pres_name: str | None = Field(None, alias="dn")
    pres_addr: str | None = Field(None, alias="da")
    pres_phone: str | None = Field(None, alias="dp")
    prescriber_dea: str | None = Field(None, alias="dea")
    prescriber_npi: str | None = Field(None, alias="npi")


class CompactMedicine(ToolModel):
    drug_name: str | None = Field(None, alias="n")
    ndc: str | None = None
    inventory_bucket: str | None = Field(None, alias="ib")
    lot_number: str | None = Field(None, alias="lot")
    expiration_date: str | None = Field(None, alias="exp")
    pack_size: str | None = Field(None, alias="pack")
    manufacturer: str | None = Field(None, alias="mfr")
    generic_indicator: str | None = Field(None, alias="gen")
    strength: str | None = Field(None, alias="str")
    daw_code: str | None = Field(None, alias="daw")
    drug_schedule: str | None = Field(None, alias="sch")
    totals: CompactTotals | None = Field(None, alias="t")
    dispenses: list[CompactDispense] = Field(default_factory=list, alias="d")


class CompactPage(ToolModel):
    source_page: int = Field(alias="p", ge=1)
    pharmacy: CompactPharmacy = Field(default_factory=CompactPharmacy, alias="ph")
    grand_total: CompactGrandTotal = Field(default_factory=CompactGrandTotal, alias="gt")
    medicines: list[CompactMedicine] = Field(default_factory=list, alias="m")


def _inline_schema(schema: dict[str, Any]) -> dict[str, Any]:
    definitions = schema.get("$defs", {})

    def expand(node: Any) -> Any:
        if isinstance(node, list):
            return [expand(item) for item in node]
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


def extraction_tool() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Extract visible page fields sparsely; omit absent values.",
            "strict": False,
            "parameters": _inline_schema(CompactPage.model_json_schema(by_alias=True)),
        },
    }


def _render_pages(pdf_bytes: bytes) -> list[str]:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    encoded: list[str] = []
    try:
        for page in document:
            pixmap = page.get_pixmap(dpi=settings.DOCUMENT_LLM_RENDER_DPI, alpha=False)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            buffer = BytesIO()
            image.save(buffer, format="JPEG", quality=88, optimize=True)
            encoded.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
    finally:
        document.close()
    return encoded


def _extract_page(image: str, page_number: int, page_count: int) -> tuple[int, dict, dict]:
    client = OpenAI(
        api_key=settings.OPENROUTER_API_KEY,
        base_url=settings.OPENROUTER_BASE_URL,
        timeout=settings.DOCUMENT_LLM_TIMEOUT_SECONDS,
        max_retries=1,
    )
    started = perf_counter()
    response = client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        temperature=0,
        max_tokens=settings.DOCUMENT_LLM_MAX_OUTPUT_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Extract page {page_number} of {page_count}."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image}"},
                    },
                ],
            },
        ],
        tools=[extraction_tool()],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        extra_body={
            "provider": {
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
            }
        },
    )
    calls = response.choices[0].message.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != TOOL_NAME:
        raise ValueError(f"Page {page_number} did not return the required tool call")
    page = CompactPage.model_validate_json(calls[0].function.arguments)
    if page.source_page != page_number:
        raise ValueError(f"Page number mismatch: expected {page_number}, got {page.source_page}")
    usage = response.usage
    usage_extra = getattr(usage, "model_extra", None) or {}
    metrics = {
        "seconds": perf_counter() - started,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "cost": getattr(usage, "cost", None) or usage_extra.get("cost"),
    }
    return page_number, page.model_dump(exclude_none=True), metrics


def _merge_pages(pages: list[dict]) -> dict[str, Any]:
    report: dict[str, Any] = {"pharmacy": {}, "grand_total": {}, "medicines": []}
    medicines: dict[str, dict] = {}
    for page in pages:
        for key, value in page.get("pharmacy", {}).items():
            if value is not None and report["pharmacy"].get(key) is None:
                report["pharmacy"][key] = value
        if any(value is not None for value in page.get("grand_total", {}).values()):
            report["grand_total"].update(page["grand_total"])
        for medicine in page.get("medicines", []):
            if not medicine.get("drug_name") or not medicine.get("ndc"):
                continue
            key = medicine["ndc"]
            target = medicines.setdefault(key, {**medicine, "dispenses": [], "totals": {}})
            if len(medicine["drug_name"]) > len(target["drug_name"]):
                target["drug_name"] = medicine["drug_name"]
            if medicine.get("totals"):
                target["totals"].update(medicine["totals"])
            for dispense in medicine.get("dispenses", []):
                dispense["source_page"] = page["source_page"]
                dispense["warnings"] = []
                target["dispenses"].append(dispense)
    report["medicines"] = list(medicines.values())
    return report


def process_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    if not settings.OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY is required for Gemini extraction")
    started = perf_counter()
    images = _render_pages(pdf_bytes)
    results: dict[int, dict] = {}
    metrics: list[dict] = []
    with ThreadPoolExecutor(max_workers=settings.DOCUMENT_LLM_MAX_CONCURRENCY) as executor:
        futures = [
            executor.submit(_extract_page, image, index, len(images))
            for index, image in enumerate(images, start=1)
        ]
        for future in as_completed(futures):
            page_number, page, page_metrics = future.result()
            results[page_number] = page
            metrics.append(page_metrics)
    logger.info(
        "Gemini dispense extraction complete: pages={pages} seconds={seconds:.2f} "
        "prompt_tokens={prompt} completion_tokens={completion} cost={cost}",
        pages=len(images),
        seconds=perf_counter() - started,
        prompt=sum(item["prompt_tokens"] or 0 for item in metrics),
        completion=sum(item["completion_tokens"] or 0 for item in metrics),
        cost=sum(float(item["cost"] or 0) for item in metrics),
    )
    return _merge_pages([results[index] for index in sorted(results)])


def dump_tool_schema() -> str:
    """Return the compact tool schema for diagnostics and tests."""
    return json.dumps(extraction_tool(), sort_keys=True)
