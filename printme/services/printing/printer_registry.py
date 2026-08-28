"""The fixed set of USB-connected printers (CLAUDE.md) - the admin
picks one from a dropdown; nothing is ever hardcoded to a single
printer."""

from config import PRINTER_BORDERLESS_CAPABLE, PRINTER_NAMES


def available_printers():
    """Printer names for the admin's dropdown."""
    return list(PRINTER_NAMES)


def is_valid_printer(name):
    return name in PRINTER_NAMES


def borderless_capable(name):
    """True/False if diagnosed (see scripts/printer_capabilities.py),
    None if not yet diagnosed on the real hardware."""
    return PRINTER_BORDERLESS_CAPABLE.get(name)
