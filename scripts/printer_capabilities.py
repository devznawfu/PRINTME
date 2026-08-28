"""Dev-only, read-only diagnostic: what paper sizes and media types does
each configured printer's real Windows driver actually support?

This exists because true edge-to-edge ("borderless") printing needs the
print driver set to a borderless paper mode, and that's entirely
driver/model-specific - it can't be verified from the Linux dev
container this project is normally developed in (no printer/USB access
there). Run this ONCE on the real admin PC with the printers connected
and paste the full output back so the borderless print-driver feature
can be built from real data instead of guesses. Nothing here writes
anything - OpenPrinter/GetPrinter/DeviceCapabilities are all read-only
Win32 calls.

Usage (on the admin PC, from the repo root, with the venv set up):
    venv\\Scripts\\python.exe scripts\\printer_capabilities.py > printer_capabilities_output.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import win32print

from config import PRINTER_NAMES

# pywin32 doesn't expose these as named attributes on win32print (confirmed:
# win32print.DC_PAPERS raises AttributeError on the admin PC's pywin32
# install) - these are the raw DeviceCapabilities fMode values straight from
# the Win32 API (wingdi.h / MSDN's DeviceCapabilities docs), not something
# pywin32 wraps.
DC_PAPERS = 2
DC_PAPERSIZE = 3
DC_PAPERNAMES = 16
DC_MEDIATYPENAMES = 34
DC_MEDIATYPES = 35

# Wording varies by driver/manufacturer - this is just a convenience
# highlight over the raw table below, not something to trust blindly.
BORDERLESS_HINT_WORDS = ("borderless", "full bleed", "edge", "photo")


def _query(printer_name, port, capability, capability_name):
    try:
        result = win32print.DeviceCapabilities(printer_name, port, capability)
    except Exception as exc:
        print(f"    {capability_name}: could not query ({exc})")
        return None
    if not isinstance(result, (list, tuple)):
        print(f"    {capability_name}: not supported by this driver")
        return None
    return list(result)


def report_printer(printer_name):
    print(f"\n=== {printer_name} ===")
    try:
        handle = win32print.OpenPrinter(printer_name)
    except Exception as exc:
        print(f"  could not open ({exc}) - is it installed/connected/powered on?")
        return
    try:
        info = win32print.GetPrinter(handle, 2)
        port = info["pPortName"]
        print(f"  port: {port}")
    except Exception as exc:
        print(f"  could not read port ({exc})")
        return
    finally:
        win32print.ClosePrinter(handle)

    paper_ids = _query(printer_name, port, DC_PAPERS, "DC_PAPERS")
    paper_names = _query(printer_name, port, DC_PAPERNAMES, "DC_PAPERNAMES")
    paper_sizes = _query(printer_name, port, DC_PAPERSIZE, "DC_PAPERSIZE")

    if paper_ids and paper_names and paper_sizes:
        # DC_PAPERSIZE's real return shape from pywin32 hasn't been
        # confirmed (assuming (width, height) tenths-of-mm tuples per
        # POINT-array structs failed on the real printer with a str, not
        # an int) - stay defensive and print the raw value on anything
        # unexpected instead of crashing, so this still gets us real
        # ground-truth data to build the actual parsing from.
        print("  paper sizes (id, name, size):")
        hints = []
        for pid, name, size in zip(paper_ids, paper_names, paper_sizes):
            clean_name = name.strip("\x00").strip() if isinstance(name, str) else repr(name)
            try:
                w, h = size
                w_mm, h_mm = float(w) / 10, float(h) / 10
                size_repr = f"{w_mm:.1f} x {h_mm:.1f} mm"
            except (TypeError, ValueError):
                size_repr = f"RAW (unrecognized shape): {size!r}"
            print(f"    {pid:>4}  {clean_name!r:30}  {size_repr}")
            if any(word in clean_name.lower() for word in BORDERLESS_HINT_WORDS):
                hints.append((pid, clean_name))
        if hints:
            print("  possible borderless/photo paper entries (verify manually):")
            for pid, name in hints:
                print(f"    id={pid}  name={name!r}")
        else:
            print("  no paper name matched the borderless/photo hint words above")

    media_ids = _query(printer_name, port, DC_MEDIATYPES, "DC_MEDIATYPES")
    media_names = _query(printer_name, port, DC_MEDIATYPENAMES, "DC_MEDIATYPENAMES")
    if media_ids and media_names:
        print("  media types (id, name) - glossy vs. plain is often exposed here:")
        for mid, name in zip(media_ids, media_names):
            clean_name = name.strip("\x00").strip() if isinstance(name, str) else repr(name)
            print(f"    {mid:>4}  {clean_name!r}")


def main():
    print("PRINTME! printer capability diagnostic - read-only, writes nothing.")
    for printer_name in PRINTER_NAMES:
        report_printer(printer_name)


if __name__ == "__main__":
    main()
