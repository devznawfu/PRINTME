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

import time
from pathlib import Path

import pymupdf
from PIL import Image, ImageWin

from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.printer_registry import available_printers, is_valid_printer

# PDF page geometry is in points (1/72in); render at the same 300 DPI
# the rest of the pipeline uses (printme/layout_engine/sizes.py).
_PDF_ZOOM = 300 / 72


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


def _draw_images(images, printer_name):
    """Print every image in `images` as its own page of one document,
    scaled to fit the printer's printable area (preserving aspect
    ratio, centered) - GDI's stretch-blit handles resampling, so this
    is correct regardless of the printer's native DPI vs. the source
    images' 300 DPI."""
    import win32con
    import win32ui

    hdc = win32ui.CreateDC()
    hdc.CreatePrinterDC(printer_name)
    hdc.StartDoc("PRINTME print job")
    try:
        for img in images:
            hdc.StartPage()
            page_w = hdc.GetDeviceCaps(win32con.HORZRES)
            page_h = hdc.GetDeviceCaps(win32con.VERTRES)
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

    def print_file(self, file_path, printer_name, copies=1, grayscale=False):
        if not is_valid_printer(printer_name):
            raise PrintError(f"unknown printer: {printer_name!r}")
        if copies < 1:
            raise PrintError("copies must be at least 1")

        try:
            images = _images_for(file_path, grayscale=grayscale)
            # No driver-level copy count is used (StartDoc/EndDoc is
            # per-copy below), so this loop is what "copies" means here.
            for _ in range(copies):
                _draw_images(images, printer_name)
        except Exception as exc:
            raise PrintError(f"could not print {file_path} to {printer_name}: {exc}") from exc

        return f"win32-{printer_name}-{int(time.time())}"
