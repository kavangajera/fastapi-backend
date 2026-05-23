import json
import re
import cv2
from pylibdmtx.pylibdmtx import decode

try:
    from zxingcpp import BarcodeFormat, read_barcodes
    _ZXING_AVAILABLE = True
except Exception:
    _ZXING_AVAILABLE = False

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
        "raw_data": raw_string
    }
    
    # 1. Extract GTIN (Starts with 01, exactly 14 digits)
    gtin_match = re.search(r'01(\d{14})', normalized)
    if gtin_match:
        parsed_data["gtin"] = gtin_match.group(1)
        
    # 2. Extract Expiration Date (Starts with 17, exactly 6 digits YYMMDD)
    expiry_match = re.search(r'17(\d{6})', normalized)
    if expiry_match:
        yy, mm, dd = expiry_match.group(1)[0:2], expiry_match.group(1)[2:4], expiry_match.group(1)[4:6]
        parsed_data["expiration_date"] = f"20{yy}-{mm}-{dd}"
        
    # 3. Extract Serial Number (Starts with 21, alphanumeric, stops at next identifier or end)
    # Matches the exact pattern from your bottle label image
    sn_match = re.search(r'21([A-Z0-9]{1,20})', normalized)
    if sn_match:
        parsed_data["serial_number"] = sn_match.group(1)
        
    # 4. Extract Lot Number (Starts with 10, alphanumeric)
    lot_match = re.search(r'10([A-Z0-9]{1,20})', normalized)
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
        detected_codes = _decode_candidate(candidate)
        if detected_codes:
            break

    if not detected_codes:
        return json.dumps({"error": "No DataMatrix barcode detected in the image."}, indent=4)

    results = []
    for code in detected_codes:
        # Decode bytes payload to string (pylibdmtx returns bytes, zxing returns str)
        raw_string = code.data.decode('utf-8') if hasattr(code, "data") else str(code)
        
        # Parse the structured GS1 data blocks
        structured_data = parse_gs1_datamatrix(raw_string)
        results.append(structured_data)

    # Return clean JSON string
    if len(results) == 1:
        return json.dumps(results[0], indent=4)
    else:
        return json.dumps({"detected_items": results}, indent=4)

def _generate_candidates(image):
    candidates = []

    # Downscale large images to speed up decoding
    h, w = image.shape[:2]
    max_w = 1600
    if w > max_w:
        scale = max_w / float(w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    candidates.append(gray)

    # Contrast enhancement helps with printed labels
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    candidates.append(enhanced)

    # Adaptive threshold tends to help DataMatrix finder patterns
    thresh = cv2.adaptiveThreshold(
        enhanced,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        5,
    )
    candidates.append(thresh)

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

        pad = 10
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
        candidates.append(crop)

    return candidates

def _decode_candidate(candidate):
    if _ZXING_AVAILABLE:
        results = _decode_with_zxing(candidate)
        if results:
            return results

    # Fallback to pylibdmtx (libdmtx)
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