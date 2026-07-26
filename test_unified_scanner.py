import json
import time
import os
from services.barcode_scanner import BarcodeScannerService
from services.datamatrix_scanner import scan_image_bytes

def test_unified(filepath):
    print(f"\n{'='*50}\nTesting {filepath}\n{'='*50}")
    
    try:
        with open(filepath, "rb") as f:
            image_bytes = f.read()
    except Exception as e:
        print(f"Failed to read file: {e}")
        return

    # 1. Test Barcode Scanner (pyzbar)
    print("\n--- 1. Testing Barcode Scanner (pyzbar) ---")
    barcode_start = time.perf_counter()
    barcode_service = BarcodeScannerService()
    try:
        barcode_result = barcode_service.process_barcode_image(filepath)
        print(f"Time: {(time.perf_counter() - barcode_start)*1000:.2f} ms")
        print(json.dumps(barcode_result, indent=2))
    except Exception as e:
        print(f"Barcode Scanner Error: {e}")

    # 2. Test DataMatrix Scanner (zxing-cpp + pylibdmtx)
    print("\n--- 2. Testing DataMatrix Scanner (zxing/pylibdmtx) ---")
    dmtx_start = time.perf_counter()
    try:
        dmtx_result = scan_image_bytes(image_bytes, debug=False)
        print(f"Time: {(time.perf_counter() - dmtx_start)*1000:.2f} ms")
        print(json.dumps(dmtx_result, indent=2))
    except Exception as e:
        print(f"DataMatrix Scanner Error: {e}")

if __name__ == "__main__":
    test_unified(os.path.abspath("IMG_2999.HEIC"))
