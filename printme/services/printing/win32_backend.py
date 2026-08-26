"""Real printer backend for the Windows target deployment (CLAUDE.md:
win32-based, local, never network/IPP). Only ever imported behind the
sys.platform == "win32" check in printme/services/printing/__init__.py
- win32api isn't installed on non-Windows platforms at all (matches
requirements.txt's own pywin32==312; sys_platform == "win32" gating).

Uses the ShellExecute "printto" verb rather than the low-level
win32print spooler API directly: win32print's raw interface sends
bytes straight to the print queue and expects them already in a
format the printer driver understands (PostScript/PCL/etc) - it does
not rasterize a PDF, JPEG, or PNG for you. ShellExecute delegates that
rendering to whichever application Windows already has registered to
open .pdf/.jpg/.png (Edge, Photos, etc.), the same mechanism as
right-click > Print in Explorer, and its "printto" verb lets you name
a *specific* printer instead of the system default - which is exactly
what the admin's printer dropdown needs.

Known limitation, unverifiable from a Linux dev container: ShellExecute
is fire-and-forget and hands off to whatever app is registered as the
default handler for that file type - depending on that app, printing
may not be fully silent (a window, or even a dialog, could appear).
Confirm actual behavior on the real admin PC.
"""

import time

import win32api

from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.printer_registry import available_printers, is_valid_printer


class Win32PrinterBackend(PrinterBackend):
    def list_printers(self):
        return available_printers()

    def print_file(self, file_path, printer_name, copies=1):
        if not is_valid_printer(printer_name):
            raise PrintError(f"unknown printer: {printer_name!r}")
        if copies < 1:
            raise PrintError("copies must be at least 1")

        try:
            # ShellExecute's print verb has no native copies parameter -
            # relaunching the handler once per copy is the standard
            # workaround (each copy briefly reopens the handler app).
            for _ in range(copies):
                win32api.ShellExecute(0, "printto", str(file_path), f'"{printer_name}"', ".", 0)
        except Exception as exc:
            raise PrintError(f"could not send {file_path} to {printer_name}: {exc}") from exc

        return f"win32-{printer_name}-{int(time.time())}"
