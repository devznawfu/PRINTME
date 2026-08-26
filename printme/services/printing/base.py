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
    def print_file(self, file_path, printer_name, copies=1, grayscale=False):
        """Send file_path to printer_name. Raises PrintError on
        failure. Returns an opaque, backend-specific job identifier.
        grayscale=True means print in black and white only."""
