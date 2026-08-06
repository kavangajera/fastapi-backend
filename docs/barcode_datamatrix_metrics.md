# Barcode and DataMatrix Metrics

Date: 2026-05-23
Owner: TBD
Hardware: MacBook Pro M3
OS: macOS
Python: TBD

## Scope
This document tracks:
- NDC from 1D barcode + API lookup latency
- GS1 DataMatrix scan latency

## Metrics
All timings are end-to-end and include image load and decode.

| Flow | Median (ms) | P95 (ms) | Notes |
| --- | --- | --- | --- |
| 1D barcode decode (pyzbar) | TBD | TBD | Image: TBD |
| NDC API lookup | TBD | TBD | Endpoint: TBD |
| DataMatrix decode (zxing-cpp + pylibdmtx fallback) | TBD | TBD | Image: TBD |

## How to Measure
1. Use the same image set for every run (10+ images).
2. Run each flow 30+ times and compute median and P95.
3. Record OS, CPU, and Python version.

Example snippet (run locally):

```python
import time

start = time.perf_counter()
# call decode
elapsed_ms = (time.perf_counter() - start) * 1000
print(f"decode ms: {elapsed_ms:.2f}")
```

## Setup (Python)
Install Python deps with uv:

```bash
uv sync
```

### Barcode (1D) + QR (pyzbar)
Python package:
- pyzbar

Native library:
- zbar

### DataMatrix
Python packages:
- zxing-cpp
- pylibdmtx
- opencv-python

Native library:
- libdmtx

## Native Dependencies

### macOS (Homebrew)
```bash
brew install zbar libdmtx
```

### Linux (Ubuntu/Debian)
```bash
sudo apt-get update
sudo apt-get install -y libzbar0 libdmtx0a
```

### Windows
Use one of the following approaches:

Option A: vcpkg
- Install vcpkg and then:
```bash
vcpkg install zbar libdmtx
```

Option B: Prebuilt binaries
- Install zbar and libdmtx from trusted sources and ensure their DLLs are on PATH.

## Notes
- The decoder prefers zxing-cpp for DataMatrix and falls back to pylibdmtx.
- If the decoder cannot find native libraries, ensure the OS-specific libs are installed.

## macOS: Homebrew libs not found even after `brew install`

**Symptom:** `brew install zbar libdmtx` succeeds, `import pyzbar` succeeds, but
`pyzbar.pyzbar.decode(...)` raises `ImportError: Unable to find zbar shared
library` (or pylibdmtx does the equivalent) the first time a scan is attempted.

**Cause:** both packages resolve their native library via
`ctypes.util.find_library`, which only searches the system's default dynamic
linker paths (`/usr/lib`, `/System/Library`, etc). Homebrew installs to
`/opt/homebrew` (Apple Silicon) or `/usr/local` (Intel), which is not on that
default search path, so the lookup fails even though the `.dylib` is present
on disk. This is a macOS/Homebrew-only issue — Debian/Ubuntu's
`apt-get install libzbar0 libdmtx0a` registers libraries with `ldconfig`, so
production (Linux) is unaffected.

**Fix applied:** `services/_native_libs.py::ensure_macos_homebrew_lib_paths()`
runs before the `pyzbar`/`pylibdmtx` imports in `services/barcode_scanner.py`
and `services/datamatrix_scanner.py`. On `darwin` only, it probes
`/opt/homebrew/opt/{zbar,libdmtx}/lib` and `/usr/local/opt/{zbar,libdmtx}/lib`
and, if present, appends them to `DYLD_LIBRARY_PATH` /
`DYLD_FALLBACK_LIBRARY_PATH` for the current process before the native
extensions load. No-op on Linux/Windows; no code change needed there.

## Test run — 2026-08-06 (MacBook, Apple Silicon, after the fix above)

Ran `services.barcode_scanner.BarcodeScannerService` (pyzbar) and
`services.datamatrix_scanner.scan_image_bytes` (zxing-cpp → pylibdmtx
fallback) directly against the three sample images, no Kafka involved.

| Image | 1D Barcode (pyzbar) | GS1 DataMatrix (zxing-cpp/pylibdmtx) |
| --- | --- | --- |
| `IMG_2995.HEIC` | ❌ not detected | ✅ decoded — GTIN `00324208830604`, lot `03242088306042110001`, exp `2026-01-31` |
| `IMG_2999.HEIC` | ✅ decoded — NDC `0006027731`, GTIN `300060277313` | ❌ not detected |
| `20260331_181340184_iOS.heic` | ✅ decoded — NDC `7590700530`, GTIN `375907005305` | ❌ not detected |

**Per-image success rate:** barcode 2/3 (67%), datamatrix 1/3 (33%) — but
every image had **at least one** code type decode successfully (3/3), and
each image appears to contain only one code type (a 1D barcode *or* a GS1
DataMatrix, not both), which is consistent with the 0%/100% split per image
rather than a decoder failure. The one DataMatrix miss (`IMG_2995.HEIC` has
no barcode) took ~260ms; the two DataMatrix misses on barcode-only images
took ~33s each because `_generate_candidates` exhausts its full rotation/ROI
sweep before giving up — see "Possible follow-up" below.

**Possible follow-up (not done as part of this check):** the ~33s worst-case
DataMatrix miss cost is entirely candidate-generation overhead
(`services/datamatrix_scanner.py::_generate_candidates` /
`_add_gradient_rois`) trying every rotation/threshold/ROI combination on an
image with no DataMatrix present. Worth capping if this pipeline runs
synchronously anywhere latency-sensitive; today it's fine since it runs off
the Kafka `barcode` worker.
