"""macOS-only helper so `pyzbar`/`pylibdmtx` can find Homebrew-installed
shared libraries.

On Linux (production), `apt-get install libzbar0 libdmtx0a` registers the
libraries with ldconfig and `ctypes.util.find_library` finds them with no
extra setup. On macOS, Homebrew installs to a prefix (`/opt/homebrew` on
Apple Silicon, `/usr/local` on Intel) that isn't on the default dynamic
linker search path, so `ctypes.util.find_library('zbar')` fails even after
`brew install zbar libdmtx`. This only widens `DYLD_LIBRARY_PATH` /
`DYLD_FALLBACK_LIBRARY_PATH` for the current process before those packages
are imported; it is a no-op on any other platform.
"""

import os
import sys

_DONE = False

_BREW_PREFIXES = ("/opt/homebrew", "/usr/local")
_FORMULAS = ("zbar", "libdmtx")


def ensure_macos_homebrew_lib_paths() -> None:
    global _DONE
    if _DONE or sys.platform != "darwin":
        return
    _DONE = True

    lib_dirs = []
    for prefix in _BREW_PREFIXES:
        for formula in _FORMULAS:
            lib_dir = os.path.join(prefix, "opt", formula, "lib")
            if os.path.isdir(lib_dir):
                lib_dirs.append(lib_dir)

    if not lib_dirs:
        return

    for var in ("DYLD_LIBRARY_PATH", "DYLD_FALLBACK_LIBRARY_PATH"):
        existing = os.environ.get(var, "")
        merged = ":".join(dict.fromkeys([*lib_dirs, *existing.split(":")] if existing else lib_dirs))
        os.environ[var] = merged
