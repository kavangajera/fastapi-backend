"""Gemini vision extraction for dispense reports that do not match the legacy layout."""

from __future__ import annotations

import base64
import copy
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from io import BytesIO
from time import perf_counter
from typing import Any

import fitz
from loguru import logger
from openai import OpenAI
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.config import settings
from services.extraction_errors import NoExtractableDataError
from services.ndc_utils import to_ndc11
from services.report_service import compute_medicine_totals

TOOL_NAME = "extract_dispense_page"
SYSTEM_PROMPT = """Extract exact visible pharmacy data from one page; call the tool once.
The image controls layout. Copy strings exactly; never infer, calculate, repair, or merge.
Omit absent fields. Ignore repeated headers and examples.
Call the tool exactly once for every page, no matter its content or layout — never respond
without calling it. If a page has no medicine/dispense rows at all (a cover page, signature
page, blank page, or a totals-only page with no drug/patient rows), still call the tool and
pass an empty medicines list rather than refusing or describing the page in plain text.
Summary (Total For/Packs/TotalRxCount/no patient or RX): d=[]; Qty Disp->t.qd,
Packs->t.pk, TotalRxCount->t.rx. Detail: every row under its drug+NDC;
stacked Qty Disp/Qty Ord->qd/qo. A combined Qty/Dys column stacks two numbers: the
quantity on top, usually with decimals (180.000, 15.000), and the days supply below it as a
bare integer (90, 30). qd is always the quantity, never the days number; put the days in ds.
Price->pr, cash/retail->cp, total->tp;
Ref#/Ref->ref, explicit Reference Number->rno. Report FROM/To->rf/rt; Date:->rd.
x=true only for a visibly clipped or continuing row. Never create fake dispense rows.
NDC lives inside the drug column (e.g. "Drug Dispensed"), usually printed on its own line
directly above the drug name; take it from there even when no NDC header exists. Numbers
under other columns are never the NDC: an Ins\\Bin column holds a carrier code (HOR, MMS2,
AMR, CIGNA) plus a 6-digit BIN (610606, 610014) — these are insurance routing values, not a
drug. Never emit a medicine whose name is a carrier or whose ndc is a BIN.
Keys: root p=page, ph=pharmacy, gt=grand total, m=medicines. Pharmacy n=name,
a=address, ph=phone, fx=fax, rd=report date, rf/from, rt/to. Medicine n=drug,
ndc=NDC verbatim, keep printed hyphens/spaces, never pad or strip,
ib=inventory, lot=lot, exp=expiration, pack=pack size, mfr=manufacturer,
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

    @field_validator("ndc", mode="before")
    @classmethod
    def _normalize_ndc(cls, value: Any) -> Any:
        """Fold a printed NDC ("12345-6789-01", "0378-4275-77") to 11 digits.

        Done here rather than in the prompt because converting a 10-digit
        NDC needs the printed segment shape, which stripping would destroy.
        Normalizing at extraction also keeps `_merge_pages` keyed
        consistently, so the same drug printed dashed on one page and plain
        on another collapses into one medicine instead of two.

        A value that cannot be normalized is kept verbatim (not dropped) so
        the review UI shows what was printed and tier-1 can flag it.
        """
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        return to_ndc11(stripped) or (stripped or None)


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
            # Grammar-constrained decoding: the model literally cannot emit
            # a token that violates the schema, which is what actually
            # prevents malformed function-call JSON (vs. just retrying
            # after the fact). Compatible here because every model already
            # sets extra="forbid" (-> additionalProperties: false) and all
            # fields are optional/nullable, matching what strict mode
            # requires from the schema shape.
            "strict": True,
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


_NUDGE = (
    "You must call the extract_dispense_page tool exactly once for this page. "
    "If the page has no medicine/dispense rows (a cover, signature, blank, or "
    "totals-only page), call the tool anyway with an empty medicines list — "
    "do not respond without calling the tool."
)


def _call_extraction_tool(
    client: OpenAI, image: str, page_number: int, page_count: int, *, nudge: bool = False
):
    messages: list[dict[str, Any]] = [
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
    ]
    if nudge:
        messages.append({"role": "user", "content": _NUDGE})
    return client.chat.completions.create(
        model=settings.OPENROUTER_MODEL,
        temperature=0,
        max_tokens=settings.DOCUMENT_LLM_MAX_OUTPUT_TOKENS,
        messages=messages,
        tools=[extraction_tool()],
        tool_choice={"type": "function", "function": {"name": TOOL_NAME}},
        extra_body={
            "provider": {
                "require_parameters": True,
                "data_collection": "deny",
                "zdr": True,
            },
            # This is a direct structured-extraction call, not a task that
            # benefits from chain-of-thought. Gemini 2.5's thinking tokens
            # otherwise draw from the same max_tokens budget as the actual
            # function-call output, and on dense pages (many rows/fields)
            # that starves the JSON generation and truncates it mid-object,
            # which the API reports as MALFORMED_FUNCTION_CALL.
            "reasoning": {"enabled": False},
        },
    )


_MAX_PAGE_ATTEMPTS = 4


def _extract_page(image: str, page_number: int, page_count: int) -> tuple[int, dict, dict]:
    """Extract one page. A page that genuinely has nothing to extract (cover,
    signature, blank, totals-only) is not a failure — every field on
    `CompactPage` is optional, so an empty page is valid output. Gemini's
    function-call generation is not perfectly reliable on dense pages (it
    can truncate mid-JSON, reported as MALFORMED_FUNCTION_CALL) even with
    reasoning disabled and a generous token budget, so retry a few times
    before giving up. If it still never returns a valid tool call, that one
    page is treated as empty rather than failing the whole multi-page
    document; whether the *document as a whole* is a dispense report is
    judged once, after all pages are merged (see `process_pdf`)."""
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
                "Page {p} attempt {a}/{n} raised {error} — retrying",
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
            "Page {p} attempt {a}/{n} did not return a tool call",
            p=page_number,
            a=attempt,
            n=_MAX_PAGE_ATTEMPTS,
        )

    page_failed = False
    if len(calls) != 1 or calls[0].function.name != TOOL_NAME:
        logger.warning(
            "Page {p} never returned a tool call after {n} attempts — treating as an empty page",
            p=page_number,
            n=_MAX_PAGE_ATTEMPTS,
        )
        # Distinct from a page that legitimately had nothing on it. If every
        # page ends up here the cause is systemic (provider outage, rate
        # limiting, exhausted credit) and must not be reported as "this
        # isn't a dispense report" — see `process_pdf`.
        page_failed = True
        page = CompactPage(source_page=page_number)
    else:
        page = CompactPage.model_validate_json(calls[0].function.arguments)
        if page.source_page != page_number:
            # Diagnostic field only (merging is keyed by NDC, not
            # source_page) — trust our own loop index over a model that
            # miscounted rather than failing the page.
            logger.warning(
                "Page number mismatch: expected {expected}, model said {got} — using {expected}",
                expected=page_number,
                got=page.source_page,
            )
            page.source_page = page_number

    usage = getattr(response, "usage", None)
    usage_extra = getattr(usage, "model_extra", None) or {}
    metrics = {
        "seconds": perf_counter() - started,
        "prompt_tokens": getattr(usage, "prompt_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None),
        "cost": getattr(usage, "cost", None) or usage_extra.get("cost"),
        "failed": page_failed,
    }
    return page_number, page.model_dump(exclude_none=True), metrics


def _is_phantom_medicine(medicine: dict[str, Any]) -> bool:
    """True for a row that isn't a drug at all.

    Wide daily-log layouts put an insurance column (`Ins\\Bin`) beside the
    drug column, and the model sometimes reads a carrier code + its 6-digit
    BIN (e.g. "CIGNA" / 610606) as a drug + NDC. Those rows never carry
    dispenses and never carry a resolvable NDC.

    The two conditions are required together so real data is never dropped:
    a genuine summary-only row (a per-drug "Total For:" block) has no
    dispenses either, but it does have a valid NDC, so it is kept.
    """
    return not medicine.get("dispenses") and not to_ndc11(medicine.get("ndc"))


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
            if not medicine.get("drug_name"):
                continue
            # Not every report format prints an NDC per row (e.g. a daily
            # dispense log by patient/date rather than a per-drug summary
            # report) — fall back to the drug name so those rows still
            # merge/survive instead of being silently dropped for lacking
            # a field this particular document never had.
            key = medicine.get("ndc") or medicine["drug_name"].strip().upper()
            target = medicines.setdefault(key, {**medicine, "dispenses": [], "totals": {}})
            if len(medicine["drug_name"]) > len(target["drug_name"]):
                target["drug_name"] = medicine["drug_name"]
            if medicine.get("totals"):
                target["totals"].update(medicine["totals"])
            for dispense in medicine.get("dispenses", []):
                dispense["source_page"] = page["source_page"]
                dispense["warnings"] = []
                target["dispenses"].append(dispense)

    report["medicines"] = [m for m in medicines.values() if not _is_phantom_medicine(m)]

    # Totals are derived from the merged dispenses, not trusted from
    # whatever the extractor reported per-page — some formats (e.g. a
    # daily dispense log) never print a per-drug totals line at all, and
    # even when one is visible, summing the actual rows this document
    # produced is more reliable than a single page's printed figure once
    # dispenses span multiple pages. `packs`/`total_cost` have no
    # per-dispense equivalent, so those pass through whatever (if
    # anything) the extractor saw.
    for medicine in report["medicines"]:
        computed = compute_medicine_totals(medicine["dispenses"])
        medicine["totals"] = {
            "packs": medicine["totals"].get("packs"),
            "total_cost": medicine["totals"].get("total_cost"),
            # `compute_medicine_totals` returns Decimal for the money/qty
            # sums, which is not JSON serializable. This payload is
            # published to Kafka by the worker (`kafka_infra/producer.py`
            # json.dumps), so it must stay JSON-native. Decimals become
            # strings, matching every other extracted field; `total_rx_count`
            # is already an int and keeps its type.
            **{k: (str(v) if isinstance(v, Decimal) else v) for k, v in computed.items()},
        }

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
    report = _merge_pages([results[index] for index in sorted(results)])

    has_any_data = bool(report["medicines"]) or any(
        value is not None for value in report["grand_total"].values()
    )
    if has_any_data:
        return report

    # Nothing came back. Before blaming the document, check whether the
    # pages actually FAILED (no valid tool call after every retry) rather
    # than legitimately being empty. When every page fails the cause is
    # systemic — provider outage, rate limiting, exhausted credit — and
    # calling it "not a Drug Dispensed Report" both misdiagnoses it and,
    # because that maps to PermanentDocumentError, permanently fails a
    # perfectly good document with no retry.
    failed_pages = sum(1 for item in metrics if item.get("failed"))
    if failed_pages:
        raise RuntimeError(
            f"Extraction produced no data and {failed_pages}/{len(images)} page(s) "
            f"never returned a valid response from the model. This looks like a "
            f"provider/transport problem (outage, rate limit, or exhausted credit) "
            f"rather than a problem with the document — retrying."
        )

    raise NoExtractableDataError(
        f"No dispense/medicine data could be extracted from any of the "
        f"{len(images)} page(s) in this document — it does not appear to "
        f"be a Drug Dispensed Report."
    )


def dump_tool_schema() -> str:
    """Return the compact tool schema for diagnostics and tests."""
    return json.dumps(extraction_tool(), sort_keys=True)
