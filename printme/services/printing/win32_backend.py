"""Real printer backend for the Windows target deployment (CLAUDE.md:
win32-based, local, never network/IPP). Normally only ever imported
behind the sys.platform == "win32" check in
printme/services/printing/__init__.py - win32ui/win32con aren't
installed on non-Windows platforms at all (matches requirements.txt's
own pywin32==312; sys_platform == "win32" gating). They're imported
lazily inside _draw_images() rather than at module level specifically
so _images_for() (pure PyMuPDF/Pillow rasterization, no GDI) stays
importable and directly testable on any platform, including this dev
container.

Prints by drawing rasterized pages directly into a device context
bound to the named printer (win32ui.CreateDC().CreatePrinterDC(...) +
PIL's ImageWin.Dib), rather than the earlier ShellExecute("printto",
...) approach. ShellExecute hands the file to whatever app Windows has
registered as the default handler for that extension - the first
real-world print attempt failed exactly there ("A device attached to
the system is not functioning", from ShellExecute itself, not the
printer), so this avoids depending on that registration existing or
behaving at all. PDFs are rasterized page-by-page with PyMuPDF first
(PIL can't read PDFs) so every supported file type goes through the
same drawing code.
"""

import logging
import time
from pathlib import Path

import pymupdf
from PIL import Image, ImageWin

from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.printer_registry import available_printers, is_valid_printer

logger = logging.getLogger(__name__)

# PDF page geometry is in points (1/72in); render at the same 300 DPI
# the rest of the pipeline uses (printme/layout_engine/sizes.py).
_PDF_ZOOM = 300 / 72

# pywin32 doesn't expose these as named attributes on win32print (confirmed
# via scripts/printer_capabilities.py on the real admin PC - win32print.DC_PAPERS
# raises AttributeError there) - raw Win32 DeviceCapabilities fMode values.
_DC_PAPERS = 2
_DC_PAPERNAMES = 16


def _match_borderless_paper_id(paper_ids, paper_names, target_size_name="a4"):
    """The driver paper id for a borderless entry matching
    `target_size_name` (e.g. "A4 (Borderless) (210 x 297 mm)"), or None
    if nothing matches. A pure function over plain lists so it's
    testable without any win32 module - the actual DeviceCapabilities
    call lives in _borderless_dc(). Not hardcoded to a specific id
    (confirmed 274 for A4 on the real T420W/T430W drivers) since driver
    updates could renumber it."""
    target_size_name = target_size_name.lower()
    for pid, name in zip(paper_ids, paper_names):
        clean = (name or "").strip("\x00").strip().lower()
        if target_size_name in clean and "borderless" in clean:
            return pid
    return None


def _borderless_dc(printer_name):
    """A device context set to the driver's borderless A4 paper mode,
    or None if unavailable/unsupported for any reason. Callers must
    fall back to the normal CreatePrinterDC path on None - a live shop
    print job failing outright is worse than printing with a normal
    margin, so nothing here is allowed to raise."""
    import win32con
    import win32gui
    import win32print
    import win32ui

    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            port = win32print.GetPrinter(hprinter, 2)["pPortName"]
        finally:
            win32print.ClosePrinter(hprinter)

        paper_ids = win32print.DeviceCapabilities(printer_name, port, _DC_PAPERS)
        paper_names = win32print.DeviceCapabilities(printer_name, port, _DC_PAPERNAMES)
        paper_id = _match_borderless_paper_id(paper_ids, paper_names)
        if paper_id is None:
            logger.warning("no borderless A4 paper entry found for %r", printer_name)
            return None

        hprinter = win32print.OpenPrinter(printer_name)
        try:
            devmode = win32print.DocumentProperties(
                0, hprinter, printer_name, None, None, win32con.DM_OUT_BUFFER
            )
            devmode.PaperSize = paper_id
            devmode.Fields |= win32con.DM_PAPERSIZE
            win32print.DocumentProperties(
                0,
                hprinter,
                printer_name,
                devmode,
                devmode,
                win32con.DM_IN_BUFFER | win32con.DM_OUT_BUFFER,
            )
        finally:
            win32print.ClosePrinter(hprinter)

        raw_hdc = win32gui.CreateDC("WINSPOOL", printer_name, None, devmode)
        return win32ui.CreateDCFromHandle(raw_hdc)
    except Exception as exc:
        logger.warning("borderless setup failed for %r, falling back: %s", printer_name, exc)
        return None


def _images_for(path, grayscale=False):
    """Every page of `path` as a PIL Image (RGB, or "L" when grayscale
    is requested) - one element for a PNG/JPG, one per page for a PDF.
    PIL's ImageWin.Dib supports "L" mode directly, so grayscale pages
    don't need an RGB round-trip."""
    mode = "L" if grayscale else "RGB"
    if Path(path).suffix.lower() == ".pdf":
        doc = pymupdf.open(str(path))
        try:
            matrix = pymupdf.Matrix(_PDF_ZOOM, _PDF_ZOOM)
            return [
                Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert(mode)
                for pix in (page.get_pixmap(matrix=matrix) for page in doc)
            ]
        finally:
            doc.close()
    with Image.open(path) as img:
        return [img.convert(mode)]


def _draw_images(images, printer_name, borderless=False):
    """Print every image in `images` as its own page of one document,
    scaled to fit the printer's printable area and centered - GDI's
    stretch-blit handles resampling, so this is correct regardless of
    the printer's native DPI vs. the source images' 300 DPI.

    When borderless setup actually succeeds, the printable area is a
    few mm larger than the true sheet (driver-side bleed allowance -
    confirmed 219.0 x 306.0mm for A4 on the real T420W/T430W drivers),
    so this scales by the LARGER ratio (cover, not contain) to fill
    both edges completely, letting the small overflow get clipped by
    GDI/the printer - the standard print-industry bleed technique,
    avoiding the aspect-ratio mismatch (A4 is 210:297, the borderless
    canvas is 219.0:306.0 - not identical) from ever stretching the
    image. The scale mode keys off whether borderless setup ACTUALLY
    succeeded, not just whether it was requested - applying cover-crop
    math against the normal (smaller) printable area after a failed
    borderless setup would wrongly crop real content."""
    import win32con
    import win32ui

    hdc = _borderless_dc(printer_name) if borderless else None
    used_borderless = hdc is not None
    if hdc is None:
        hdc = win32ui.CreateDC()
        hdc.CreatePrinterDC(printer_name)

    hdc.StartDoc("PRINTME print job")
    try:
        for img in images:
            hdc.StartPage()
            page_w = hdc.GetDeviceCaps(win32con.HORZRES)
            page_h = hdc.GetDeviceCaps(win32con.VERTRES)
            if used_borderless:
                scale = max(page_w / img.width, page_h / img.height)
            else:
                scale = min(page_w / img.width, page_h / img.height)
            w, h = round(img.width * scale), round(img.height * scale)
            x, y = (page_w - w) // 2, (page_h - h) // 2
            ImageWin.Dib(img).draw(hdc.GetHandleOutput(), (x, y, x + w, y + h))
            hdc.EndPage()
    finally:
        hdc.EndDoc()
        hdc.DeleteDC()


class Win32PrinterBackend(PrinterBackend):
    def list_printers(self):
        return available_printers()

    def print_file(self, file_path, printer_name, copies=1, grayscale=False, borderless=False):
        if not is_valid_printer(printer_name):
            raise PrintError(f"unknown printer: {printer_name!r}")
        if copies < 1:
            raise PrintError("copies must be at least 1")

        try:
            images = _images_for(file_path, grayscale=grayscale)
            # No driver-level copy count is used (StartDoc/EndDoc is
            # per-copy below), so this loop is what "copies" means here.
            for _ in range(copies):
                _draw_images(images, printer_name, borderless=borderless)
        except Exception as exc:
            raise PrintError(f"could not print {file_path} to {printer_name}: {exc}") from exc

        return f"win32-{printer_name}-{int(time.time())}"
