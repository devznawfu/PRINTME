"""The fixed set of USB-connected printers (CLAUDE.md) - the admin
picks one from a dropdown; nothing is ever hardcoded to a single
printer."""

from config import PRINTER_NAMES


def available_printers():
    """Printer names for the admin's dropdown."""
    return list(PRINTER_NAMES)


def is_valid_printer(name):
    return name in PRINTER_NAMES
