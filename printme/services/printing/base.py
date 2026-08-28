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
        self, file_path, printer_name, copies=1, grayscale=False, borderless=False, page_range=None
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
        range against the real page count (see services/page_range.py)."""
