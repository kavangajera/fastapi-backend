import json
import re
from datetime import datetime
from io import BytesIO
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

from services._native_libs import ensure_macos_homebrew_lib_paths

ensure_macos_homebrew_lib_paths()

try:
    from pylibdmtx.pylibdmtx import decode

    _LIBDMTX_AVAILABLE = True
except Exception:
    decode = None
    _LIBDMTX_AVAILABLE = False

try:
    from zxingcpp import BarcodeFormat, read_barcodes

    _ZXING_AVAILABLE = True
except Exception:
    _ZXING_AVAILABLE = False

try:
    import pillow_heif

    _HEIF_AVAILABLE = True
except Exception:
    pillow_heif = None
    _HEIF_AVAILABLE = False


def parse_gs1_datamatrix(raw_string):
    """
    Parses standard GS1 AI prefixes from a raw pharmaceutical string.
    """
    # Define regex patterns for standard GS1 prefixes found on this label:
    # 01 = GTIN (14 digits)
    # 21 = Serial Number (Variable up to 20 alphanumeric characters)
    # 17 = Expiry Date (6 digits: YYMMDD)
    # 10 = Lot Number (Variable up to 20 alphanumeric characters)

    normalized = _normalize_gs1(raw_string)

    parsed_data = {
        "gtin": None,
        "serial_number": None,
        "expiration_date": None,
        "lot_number": None,
        "raw_data": raw_string,
    }

    # 1. Extract GTIN (Starts with 01, exactly 14 digits)
    gtin_match = re.search(r"01(\d{14})", normalized)
    if gtin_match:
        parsed_data["gtin"] = gtin_match.group(1)

    # 2. Extract Expiration Date (Starts with 17, exactly 6 digits YYMMDD)
    expiry_match = re.search(r"17(\d{6})", normalized)
    if expiry_match:
        yy, mm, dd = (
            expiry_match.group(1)[0:2],
            expiry_match.group(1)[2:4],
            expiry_match.group(1)[4:6],
        )
        parsed_data["expiration_date"] = f"20{yy}-{mm}-{dd}"

    # 3. Extract Serial Number (Starts with 21, alphanumeric, stops at next identifier or end)
    # Matches the exact pattern from your bottle label image
    sn_match = re.search(r"21([A-Z0-9]{1,20})", normalized)
    if sn_match:
        parsed_data["serial_number"] = sn_match.group(1)

    # 4. Extract Lot Number (Starts with 10, alphanumeric)
    lot_match = re.search(r"10([A-Z0-9]{1,20})", normalized)
    if lot_match:
        parsed_data["lot_number"] = lot_match.group(1)

    return parsed_data


def _normalize_gs1(raw_string):
    # Remove parentheses and separators, keep only AI/value sequence
    return re.sub(r"[()\s]", "", raw_string).upper()


def scan_to_json(image_path):
    # Load the image
    image = cv2.imread(image_path)
    if image is None:
        return json.dumps({"error": f"Could not load image at {image_path}"}, indent=4)

    # Detect and decode DataMatrix codes (try several preprocessed candidates)
    detected_codes = []
    for candidate in _generate_candidates(image):
        detected_codes = _decode_candidate(candidate["image"])
        if detected_codes:
            break

    if not detected_codes:
        return json.dumps({"error": "No DataMatrix barcode detected in the image."}, indent=4)

    results = []
    for code in detected_codes:
        # Decode bytes payload to string (pylibdmtx returns bytes, zxing returns str)
        raw_string = code.data.decode("utf-8") if hasattr(code, "data") else str(code)

        # Parse the structured GS1 data blocks
        structured_data = parse_gs1_datamatrix(raw_string)
        results.append(structured_data)

    # Return clean JSON string
    if len(results) == 1:
        return json.dumps(results[0], indent=4)
    else:
        return json.dumps({"detected_items": results}, indent=4)


def _decode_image_bytes(image_bytes):
    image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if image is not None:
        return image, None

    # Fallback to PIL for formats like HEIC/HEIF
    try:
        if _HEIF_AVAILABLE:
            pillow_heif.register_heif_opener()
        pil_image = Image.open(BytesIO(image_bytes)).convert("RGB")
        rgb = np.array(pil_image)
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), None
    except UnidentifiedImageError:
        return None, "Could not decode image bytes."
    except Exception as exc:
        return None, f"Could not decode image bytes: {exc}"


def scan_image_bytes(image_bytes, *, debug=False, debug_dir=None, filename=None):
    image, error = _decode_image_bytes(image_bytes)
    if image is None:
        return {"error": error or "Could not decode image bytes."}

    candidates = _generate_candidates(image)
    if debug:
        _write_debug_dump(image, candidates, debug_dir, filename)

    detected_codes = []
    for candidate in candidates:
        detected_codes = _decode_candidate(candidate["image"])
        if detected_codes:
            break

    if not detected_codes:
        return {"error": "No DataMatrix barcode detected in the image."}

    results = []
    for code in detected_codes:
        raw_string = code.data.decode("utf-8") if hasattr(code, "data") else str(code)
        structured_data = parse_gs1_datamatrix(raw_string)
        results.append(structured_data)

    if len(results) == 1:
        return results[0]

    return {"detected_items": results}


def _generate_candidates(image):
    candidates = []

    # Downscale large images to speed up decoding
    h, w = image.shape[:2]
    max_w = 1600
    if w > max_w:
        scale = max_w / float(w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates.append({"label": "gray", "image": gray})

    # Contrast enhancement helps with printed labels
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    candidates.append({"label": "clahe", "image": enhanced})

    # Adaptive threshold tends to help DataMatrix finder patterns
    thresh = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )
    candidates.append({"label": "adaptive_thresh", "image": thresh})

    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    candidates.append({"label": "otsu", "image": otsu})

    for label, src in [
        ("gray", gray),
        ("clahe", enhanced),
        ("adaptive_thresh", thresh),
        ("otsu", otsu),
    ]:
        candidates.append(
            {"label": f"{label}_rot90", "image": cv2.rotate(src, cv2.ROTATE_90_CLOCKWISE)}
        )
        candidates.append({"label": f"{label}_rot180", "image": cv2.rotate(src, cv2.ROTATE_180)})
        candidates.append(
            {"label": f"{label}_rot270", "image": cv2.rotate(src, cv2.ROTATE_90_COUNTERCLOCKWISE)}
        )

    # Try crops around square-ish contours to avoid scanning the whole image
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    img_h, img_w = gray.shape[:2]
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        area = cw * ch
        if area < 800 or area > (img_w * img_h * 0.25):
            continue
        aspect = cw / float(ch)
        if aspect < 0.7 or aspect > 1.3:
            continue

        pad = 20
        x1 = max(0, x - pad)
        y1 = max(0, y - pad)
        x2 = min(img_w, x + cw + pad)
        y2 = min(img_h, y + ch + pad)

        crop = gray[y1:y2, x1:x2]
        if crop.size == 0:
            continue
        # Upscale small crops to improve decode stability
        if crop.shape[1] < 200:
            crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        candidates.append({"label": f"crop_{len(candidates):02d}", "image": crop})

    _add_gradient_rois(gray, candidates)

    return candidates


def _add_gradient_rois(gray, candidates):
    img_h, img_w = gray.shape[:2]
    sizes = [120, 160, 220]
    max_per_size = 4

    grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    grad_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    grad_mag = cv2.magnitude(grad_x, grad_y)

    integral = cv2.integral(grad_mag)

    for size in sizes:
        if size >= img_w or size >= img_h:
            continue

        step = max(20, size // 2)
        best = []
        for y in range(0, img_h - size, step):
            y2 = y + size
            for x in range(0, img_w - size, step):
                x2 = x + size
                score = integral[y2, x2] - integral[y, x2] - integral[y2, x] + integral[y, x]
                best.append((score, x, y, x2, y2))

        best.sort(reverse=True, key=lambda item: item[0])
        for idx, (_, x1, y1, x2, y2) in enumerate(best[:max_per_size]):
            pad = max(8, size // 5)
            x1p = max(0, x1 - pad)
            y1p = max(0, y1 - pad)
            x2p = min(img_w, x2 + pad)
            y2p = min(img_h, y2 + pad)

            crop = gray[y1p:y2p, x1p:x2p]
            if crop.size == 0:
                continue
            label = f"grad_roi_{size}_{idx}"
            _add_roi_variants(crop, label, candidates)


def _add_roi_variants(crop, label, candidates):
    base = crop
    if crop.shape[0] < 160 or crop.shape[1] < 160:
        base = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
    elif crop.shape[0] < 240 or crop.shape[1] < 240:
        base = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)

    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(base)
    denoised = cv2.medianBlur(enhanced, 3)
    _, otsu = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    adaptive = cv2.adaptiveThreshold(
        denoised,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )

    variants = {
        label: base,
        f"{label}_clahe": enhanced,
        f"{label}_clahe_denoised": denoised,
        f"{label}_otsu": otsu,
        f"{label}_adaptive": adaptive,
        f"{label}_invert": cv2.bitwise_not(base),
    }

    for name, image in variants.items():
        candidates.append({"label": name, "image": image})
        candidates.append({"label": f"{name}_rot180", "image": cv2.rotate(image, cv2.ROTATE_180)})


def _write_debug_dump(image, candidates, debug_dir, filename):
    base_dir = debug_dir or "logs/datamatrix_debug"
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", filename or "image")[:80]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    run_dir = Path(base_dir) / f"{ts}_{safe_name}"
    run_dir.mkdir(parents=True, exist_ok=True)

    cv2.imwrite(str(run_dir / "original.jpg"), image)

    manifest = []
    for idx, candidate in enumerate(candidates):
        label = candidate["label"]
        img = candidate["image"]
        file_name = f"{idx:02d}_{label}.png"
        cv2.imwrite(str(run_dir / file_name), img)
        manifest.append({"label": label, "file": file_name, "shape": list(img.shape)})

    with (run_dir / "manifest.json").open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)


def _decode_candidate(candidate):
    if _ZXING_AVAILABLE:
        results = _decode_with_zxing(candidate)
        if results:
            return results

    # Fallback to pylibdmtx (libdmtx)
    if not _LIBDMTX_AVAILABLE:
        return []

    return decode(candidate, timeout=200)


def _decode_with_zxing(candidate):
    if not _ZXING_AVAILABLE:
        return []

    if len(candidate.shape) == 2:
        rgb = cv2.cvtColor(candidate, cv2.COLOR_GRAY2RGB)
    else:
        rgb = cv2.cvtColor(candidate, cv2.COLOR_BGR2RGB)

    results = read_barcodes(rgb, formats=BarcodeFormat.DataMatrix)
    texts = [r.text for r in results if r.text]
    return texts


if __name__ == "__main__":
    # Replace with your actual local image file path
    image_file = "image.png"

    json_output = scan_to_json(image_file)
    print(json_output)
