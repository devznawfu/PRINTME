"""Dry-run printer backend: records what WOULD have been printed
without touching any real hardware. Used whenever a real USB printer
isn't available (all of development, and any environment without the
win32 backend wired up) so the rest of the app can be built and tested
without physical printer access."""

import itertools
import logging

from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.printer_registry import (
    available_printers,
    is_valid_printer,
)

logger = logging.getLogger(__name__)
_job_id_counter = itertools.count(1)


class MockPrinterBackend(PrinterBackend):
    def __init__(self):
        self.print_log = []  # list of dicts - inspectable in tests/dev

    def list_printers(self):
        return available_printers()

    def print_file(self, file_path, printer_name, copies=1, grayscale=False, borderless=False):
        if not is_valid_printer(printer_name):
            raise PrintError(f"unknown printer: {printer_name!r}")
        if copies < 1:
            raise PrintError("copies must be at least 1")

        job_id = f"mock-{next(_job_id_counter)}"
        entry = {
            "job_id": job_id,
            "file_path": str(file_path),
            "printer_name": printer_name,
            "copies": copies,
            "grayscale": grayscale,
            "borderless": borderless,
        }
        self.print_log.append(entry)
        logger.info("mock print: %s", entry)
        return job_id
