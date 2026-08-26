"""Backend selection: win32 (real printers) on Windows, mock everywhere
else - so this dev container (and tests) never even attempt to import
win32api, which isn't installed on non-Windows platforms at all."""

import sys


def get_printer_backend():
    if sys.platform == "win32":
        from printme.services.printing.win32_backend import Win32PrinterBackend

        return Win32PrinterBackend()

    from printme.services.printing.mock_backend import MockPrinterBackend

    return MockPrinterBackend()
