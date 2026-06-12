import re


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
