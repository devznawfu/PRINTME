"""Printer backend interface.

CLAUDE.md: print via win32print (Windows-only), never network/IPP.
Backends are selected by platform - the real win32 backend is built
last (Phase 8), against real USB printers on the target admin PC. This
interface + the mock backend exist so every earlier feature that
"prints" has something stable to build against without needing
physical printer access during development.
"""

from abc import ABC, abstractmethod


class PrintError(Exception):
    """A print job could not be sent to the printer."""


class PrinterBackend(ABC):
    @abstractmethod
    def list_printers(self):
        """Printer names currently available through this backend."""

    @abstractmethod
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
        """Send file_path to printer_name. Raises PrintError on
        failure. Returns an opaque, backend-specific job identifier.
        grayscale=True means print in black and white only.
        borderless=True requests full-bleed edge-to-edge printing -
        only meaningful for photo sheets on a printer whose driver
        actually supports it (see printer_registry.borderless_capable);
        backends should fall back to normal printing rather than fail
        the job if it isn't achievable. page_range, if given, is a
        1-indexed list of page numbers to print (PDF only) - None means
        every page. Callers are expected to have already validated the
        range against the real page count (see services/page_range.py).

        Document-printing options (never combined with borderless=True,
        which is photo-sheet-only): paper_size is one of
        models.job.PAPER_SIZES or None (printer's current default,
        today's behavior); orientation is "portrait"/"landscape"/None
        (driver default); margin is a 0.0-1.0 fraction of the page each
        edge is inset by before scale-to-fit (0.0 = fill the printable
        area, today's default); dpi overrides the rasterization
        resolution for PDF pages (None = the pipeline's normal 300 DPI -
        see services/pdf_render.py) - this is what "print quality"
        actually means in a pipeline that always sends a fixed bitmap to
        the driver, not a driver-level quality flag. Backends that can't
        honor paper_size/orientation on a given driver must fall back to
        the current default rather than fail the job, same contract as
        borderless."""
