"""Unit tests for Win32PrinterBackend's logic (argument construction,
validation, error wrapping) - NOT a real-printing verification, which
per the printme-printing skill can only happen on the actual Windows
admin PC. win32api isn't installed on this Linux container, so it's
injected as a MagicMock into sys.modules before each import."""

import sys
from unittest.mock import MagicMock

import pytest

from printme.services.printing.base import PrintError


@pytest.fixture
def fake_pywin32(monkeypatch):
    fake_win32api = MagicMock()
    monkeypatch.setitem(sys.modules, "win32api", fake_win32api)
    # Force a fresh import bound to this test's mock, not a previous
    # test's (or a previously-imported real module's).
    monkeypatch.delitem(sys.modules, "printme.services.printing.win32_backend", raising=False)
    yield fake_win32api


def _backend(fake_pywin32):
    from printme.services.printing.win32_backend import Win32PrinterBackend

    return Win32PrinterBackend()


class TestPrintFile:
    def test_calls_shell_execute_with_printto_verb_and_quoted_printer(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        backend.print_file("/processed/doc.pdf", "DCP-T420W", copies=1)

        fake_pywin32.ShellExecute.assert_called_once()
        args = fake_pywin32.ShellExecute.call_args[0]
        assert args[1] == "printto"
        assert args[2] == "/processed/doc.pdf"
        assert args[3] == '"DCP-T420W"'

    def test_copies_relaunches_once_per_copy(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        backend.print_file("/a.pdf", "DCP-L2540DW", copies=3)
        assert fake_pywin32.ShellExecute.call_count == 3

    def test_default_copies_is_one(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        backend.print_file("/a.pdf", "DCP-L2540DW")
        assert fake_pywin32.ShellExecute.call_count == 1

    def test_returns_a_job_id(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        job_id = backend.print_file("/a.pdf", "DCP-L2540DW")
        assert job_id
        assert "DCP-L2540DW" in job_id

    def test_unknown_printer_rejected_without_calling_shell_execute(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="unknown printer"):
            backend.print_file("/a.pdf", "Not A Real Printer")
        fake_pywin32.ShellExecute.assert_not_called()

    def test_zero_copies_rejected_without_calling_shell_execute(self, fake_pywin32):
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="copies"):
            backend.print_file("/a.pdf", "DCP-L2540DW", copies=0)
        fake_pywin32.ShellExecute.assert_not_called()

    def test_shell_execute_failure_is_wrapped_in_print_error(self, fake_pywin32):
        fake_pywin32.ShellExecute.side_effect = OSError("no such handler")
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="DCP-L2540DW"):
            backend.print_file("/a.pdf", "DCP-L2540DW")


class TestListPrinters:
    def test_matches_registry(self, fake_pywin32):
        from printme.services.printing.printer_registry import available_printers

        backend = _backend(fake_pywin32)
        assert backend.list_printers() == available_printers()
