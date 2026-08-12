import re

from loguru import logger


def ndc10_to_ndc11_from_package_ndc(package_ndc: str) -> str | None:
    if not package_ndc:
        return None

    parts = package_ndc.split("-")
    if len(parts) != 3:
        return None

    labeler, product, package = parts

    if len(labeler) == 4 and len(product) == 4 and len(package) == 2:
        return f"0{labeler}{product}{package}"
    if len(labeler) == 5 and len(product) == 3 and len(package) == 2:
        return f"{labeler}0{product}{package}"
    if len(labeler) == 5 and len(product) == 4 and len(package) == 1:
        return f"{labeler}{product}0{package}"

    return None


def digits_only(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^0-9]", "", value)


# Any run of non-digits is treated as a segment separator, so "0378-4275-77",
# "0378 4275 77", "0378.4275.77" and "NDC 0378-4275-77" all split the same way.
_SEG_SPLIT_RE = re.compile(r"[^0-9]+")


def to_ndc11(raw: str | None) -> str | None:
    """Best-effort exact-11-digit NDC, or None when it cannot be certain.

    Never guesses. A 10-digit NDC only converts when the printed segment
    shape (4-4-2 / 5-3-2 / 5-4-1) is still visible, because that shape is
    what says *where* the padding zero belongs — see
    `ndc10_to_ndc11_from_package_ndc`. A bare 10-digit string has lost that
    information and is deliberately rejected rather than guessed at: it
    could pad three different ways into three different real products, and
    a plausible-but-wrong NDC silently keys `medicine_inventory`,
    reconciliation grouping, and the `MedicineNdcCache` primary key. A
    blocking MALFORMED_NDC alert a human resolves is strictly safer.

    Invariant: returns either None or exactly 11 digits. Callers rely on it.

    (`services/invoice_service._classify_ndc` and
    `services/inventory_service._normalize_ndc` implement overlapping rules
    with different return shapes and fallbacks. Consolidating them onto this
    function is worthwhile but is a separate, independently-testable change.)
    """
    if not raw:
        return None

    digits = digits_only(raw)
    if not digits:
        return None

    if len(digits) == 11:
        return digits

    if len(digits) == 10:
        segments = [s for s in _SEG_SPLIT_RE.split(raw.strip()) if s]
        if len(segments) == 3:
            return ndc10_to_ndc11_from_package_ndc("-".join(segments))
        return None

    return None


def ndc_for_storage(raw: str | None) -> str:
    """Guarantee a value that fits `Medicine.ndc` (String(11), NOT NULL).

    Last-resort guard for the `force_save=true` path, which bypasses the
    tier-1 MALFORMED_NDC gate and would otherwise hit MySQL
    ER_DATA_TOO_LONG (1406) on a hyphenated NDC.

    Clamps the *raw* string, separators included — not `digits_only`.
    Clamping digits would turn a 12-digit garbage value into 11 digits that
    pass `^\\d{11}$`, laundering garbage into a valid-looking NDC. Keeping
    the separator guarantees the value can never match, so the row stays
    visibly malformed. The untruncated original is still preserved in the
    report's `validation_errors` alert text.
    """
    if not raw:
        return ""

    normalized = to_ndc11(raw)
    if normalized:
        return normalized

    stripped = raw.strip()
    clamped = stripped[:11]
    if clamped != stripped:
        logger.warning(
            "NDC too long for column, truncated: raw={raw!r} stored={stored!r}",
            raw=stripped,
            stored=clamped,
        )
    return clamped
