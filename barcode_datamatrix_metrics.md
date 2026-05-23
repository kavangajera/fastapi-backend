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
