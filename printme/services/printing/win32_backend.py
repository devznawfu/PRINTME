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

from PIL import Image, ImageWin

from printme.services.pdf_render import rasterize_pdf, zoom_for_dpi
from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.printer_registry import available_printers, is_valid_printer

logger = logging.getLogger(__name__)

# pywin32 doesn't expose these as named attributes on win32print (confirmed
# via scripts/printer_capabilities.py on the real admin PC - win32print.DC_PAPERS
# raises AttributeError there) - raw Win32 DeviceCapabilities fMode values.
_DC_PAPERS = 2
_DC_PAPERNAMES = 16

# Driver paper-name substrings to look for per admin-selectable size (see
# models.job.PAPER_SIZES) - never a hardcoded Windows paper-size ID, same
# reasoning as the borderless lookup below: only DeviceCapabilities on the
# real driver is authoritative, and different Brother drivers may name an
# entry differently (e.g. "Folio" vs "8 1/2 x 13 in").
_PAPER_SIZE_NAME_CANDIDATES = {
    "Letter": ("letter",),
    "Folio": ("folio", "8 1/2 x 13", "8.5 x 13"),
    "A4": ("a4",),
}


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


def _match_paper_id(paper_ids, paper_names, size_name):
    """The driver paper id for a plain (non-borderless) entry matching
    one of `size_name`'s known name candidates, or None if nothing
    matches or `size_name` isn't recognized. Deliberately excludes any
    "borderless" entry - that's a distinct mode with its own bleed/
    cover-scale math (see _borderless_dc/_draw_images), not a plain
    paper size a document print should ever land on by accident."""
    candidates = _PAPER_SIZE_NAME_CANDIDATES.get(size_name)
    if not candidates:
        return None
    for pid, name in zip(paper_ids, paper_names):
        clean = (name or "").strip("\x00").strip().lower()
        if "borderless" in clean:
            continue
        if any(candidate in clean for candidate in candidates):
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


def _configured_dc(printer_name, paper_size=None, orientation=None):
    """A device context with an admin-selected paper size and/or
    orientation applied via DocumentProperties, or None if neither was
    requested, the driver has no matching paper entry, or anything else
    goes wrong. Same fail-soft contract as _borderless_dc - callers fall
    back to the plain CreatePrinterDC path (today's behavior) rather
    than fail the job, since this can't be verified against a real
    driver from this dev container."""
    if not paper_size and not orientation:
        return None

    import win32con
    import win32gui
    import win32print
    import win32ui

    try:
        hprinter = win32print.OpenPrinter(printer_name)
        try:
            port = win32print.GetPrinter(hprinter, 2)["pPortName"]
            devmode = win32print.DocumentProperties(
                0, hprinter, printer_name, None, None, win32con.DM_OUT_BUFFER
            )

            if paper_size:
                paper_ids = win32print.DeviceCapabilities(printer_name, port, _DC_PAPERS)
                paper_names = win32print.DeviceCapabilities(printer_name, port, _DC_PAPERNAMES)
                paper_id = _match_paper_id(paper_ids, paper_names, paper_size)
                if paper_id is None:
                    logger.warning(
                        "no %r paper entry found for %r, using printer default",
                        paper_size,
                        printer_name,
                    )
                else:
                    devmode.PaperSize = paper_id
                    devmode.Fields |= win32con.DM_PAPERSIZE

            if orientation:
                devmode.Orientation = (
                    win32con.DMORIENT_LANDSCAPE
                    if orientation == "landscape"
                    else win32con.DMORIENT_PORTRAIT
                )
                devmode.Fields |= win32con.DM_ORIENTATION

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
        logger.warning("paper/orientation setup failed for %r, falling back: %s", printer_name, exc)
        return None


def _images_for(path, grayscale=False, page_range=None, dpi=None):
    """Every page of `path` as a PIL Image (RGB, or "L" when grayscale
    is requested) - one element for a PNG/JPG, one per page for a PDF.
    PIL's ImageWin.Dib supports "L" mode directly, so grayscale pages
    don't need an RGB round-trip. page_range (1-indexed page numbers,
    PDF only) is ignored for non-PDF files - a single image is always
    exactly one page, and callers are expected to have already
    validated any range against the real page count (see
    services/page_range.py) before it ever reaches here. dpi overrides
    the pipeline's normal 300 DPI rasterization - see Job.print_quality/
    models.job.PRINT_QUALITIES - and only matters for PDFs; a JPG/PNG is
    already a fixed-resolution image."""
    mode = "L" if grayscale else "RGB"
    if Path(path).suffix.lower() == ".pdf":
        zoom = zoom_for_dpi(dpi) if dpi else None
        kwargs = {"zoom": zoom} if zoom else {}
        return [
            img.convert(mode)
            for img in rasterize_pdf(path, page_numbers=page_range, **kwargs)
        ]
    with Image.open(path) as img:
        return [img.convert(mode)]


def _draw_images(
    images, printer_name, borderless=False, paper_size=None, orientation=None, margin=0.0
):
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
    borderless setup would wrongly crop real content.

    margin (0.0-1.0, documents only - never combined with borderless,
    which is photo-sheet-only and means the opposite) insets the target
    rectangle by that fraction of the page on each edge before the
    contain-fit scale, so "wider margins" is real whitespace around the
    content rather than a driver setting Windows has no generic field
    for."""
    import win32con
    import win32ui

    hdc = _borderless_dc(printer_name) if borderless else None
    used_borderless = hdc is not None
    if hdc is None and not borderless and (paper_size or orientation):
        hdc = _configured_dc(printer_name, paper_size=paper_size, orientation=orientation)
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
                w, h = round(img.width * scale), round(img.height * scale)
            else:
                avail_w, avail_h = page_w * (1 - 2 * margin), page_h * (1 - 2 * margin)
                scale = min(avail_w / img.width, avail_h / img.height)
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

    def print_file(
        self,
        file_path,
        printer_name,
        copies=1,
        grayscale=False,
        borderless=False,
        page_range=None,
        paper_size=None,
        orientation=None,
        margin=0.0,
        dpi=None,
    ):
        if not is_valid_printer(printer_name):
            raise PrintError(f"unknown printer: {printer_name!r}")
        if copies < 1:
            raise PrintError("copies must be at least 1")

        try:
            images = _images_for(file_path, grayscale=grayscale, page_range=page_range, dpi=dpi)
            # No driver-level copy count is used (StartDoc/EndDoc is
            # per-copy below), so this loop is what "copies" means here.
            for _ in range(copies):
                _draw_images(
                    images,
                    printer_name,
                    borderless=borderless,
                    paper_size=paper_size,
                    orientation=orientation,
                    margin=margin,
                )
        except Exception as exc:
            raise PrintError(f"could not print {file_path} to {printer_name}: {exc}") from exc

        return f"win32-{printer_name}-{int(time.time())}"
