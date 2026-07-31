import re

with open("services/validation/tier2.py") as f:
    content = f.read()

new_module_a = """
def _parse_dispense_date(d_str: str | None) -> date | None:
    if not d_str: return None
    import dateutil.parser
    try:
        return dateutil.parser.parse(d_str).date()
    except Exception:
        return None

def _module_a(
    mi: int, ndc11: str, med: dict, cache_row, today: date, alerts: list[Alert], strict_date_check: bool = True
) -> None:
    if cache_row is None or not cache_row.found_in_fda:
        alerts.append(
            Alert(
                module="A",
                code="NDC_NOT_FOUND",
                severity="WARNING",
                message=(
                    "NDC not present in FDA Drug NDC Directory — may be a medical "
                    "device, supply, or recently launched product."
                ),
                medicine_index=mi,
                ndc=ndc11,
                actual=med.get("drug_name", ""),
                suggestion="Verify NDC manually; devices live in the FDA Device DB, not Drug.",
            )
        )
        return

    start_dt = _parse_yyyymmdd(cache_row.marketing_start_date)
    end_dt = _parse_yyyymmdd(cache_row.marketing_end_date)
    
    for di, disp in enumerate(med.get("dispenses", [])):
        date_filled_str = disp.get("date_filled")
        dispense_dt = _parse_dispense_date(date_filled_str)
        
        # Handle missing dates
        if not dispense_dt:
            if not strict_date_check:
                continue
            dispense_dt = today
            
        if start_dt and dispense_dt < start_dt:
            alerts.append(
                Alert(
                    module="A",
                    code="DRUG_DISPENSED_BEFORE_MARKETED",
                    severity="WARNING",
                    message=(
                        f"Dispensed on {dispense_dt.isoformat()} but FDA marketing start date is {start_dt.isoformat()}."
                    ),
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    actual=date_filled_str or "Missing (Used Upload Date)",
                    suggestion="Verify dispense date.",
                )
            )
            
        if end_dt and dispense_dt > end_dt:
            alerts.append(
                Alert(
                    module="A",
                    code="DRUG_DISPENSED_AFTER_DISCONTINUED",
                    severity="ERROR",
                    message=(
                        f"Dispensed on {dispense_dt.isoformat()} but FDA marketing end date is {end_dt.isoformat()}."
                    ),
                    medicine_index=mi,
                    dispense_index=di,
                    ndc=ndc11,
                    actual=date_filled_str or "Missing (Used Upload Date)",
                    suggestion="Remove from active inventory.",
                )
            )

    if end_dt:
        delta = (end_dt - today).days
        if 0 <= delta < settings.NDC_LISTING_EXPIRY_INFO_DAYS:
            alerts.append(
                Alert(
                    module="A",
                    code="NDC_LISTING_EXPIRES_SOON",
                    severity="INFO",
                    message=(
                        f"Listing expires {end_dt.isoformat()} ({delta} days). "
                    ),
                    medicine_index=mi,
                    ndc=ndc11,
                    actual=cache_row.marketing_end_date,
                )
            )
"""

content = re.sub(
    r"def _module_a\(.*?def _module_b\(",
    new_module_a + "\n\ndef _module_b(",
    content,
    flags=re.DOTALL,
)
content = content.replace(
    "_module_a(mi, ndc, drug_name, cache_row, today, alerts)",
    "_module_a(mi, ndc, med, cache_row, today, alerts, strict_date_check=True)",
)

with open("services/validation/tier2.py", "w") as f:
    f.write(content)
print("done")
