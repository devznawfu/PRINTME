import sys

import pytest

from config import PRINTER_NAMES
from printme.services.printing import get_printer_backend
from printme.services.printing.base import PrintError, PrinterBackend
from printme.services.printing.mock_backend import MockPrinterBackend
from printme.services.printing.printer_registry import (
    available_printers,
    is_valid_printer,
)


class TestGetPrinterBackend:
    def test_non_windows_returns_mock_backend(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert isinstance(get_printer_backend(), MockPrinterBackend)

    def test_windows_returns_win32_backend(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")

        from printme.services.printing.win32_backend import Win32PrinterBackend

        assert isinstance(get_printer_backend(), Win32PrinterBackend)


class TestPrinterRegistry:
    def test_available_printers_matches_claude_md_list(self):
        assert available_printers() == list(PRINTER_NAMES)
        assert set(available_printers()) == {
            "Brother DCP-L2540DW series",
            "Brother DCP-T420W",
            "Brother DCP-T430W",
        }

    def test_is_valid_printer(self):
        assert is_valid_printer("Brother DCP-L2540DW series") is True
        assert is_valid_printer("HP LaserJet") is False

    def test_available_printers_returns_a_fresh_list_not_shared_state(self):
        a = available_printers()
        a.append("tampered")
        assert "tampered" not in available_printers()


class TestPrinterBackendIsAbstract:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            PrinterBackend()

    def test_incomplete_subclass_cannot_be_instantiated(self):
        class Incomplete(PrinterBackend):
            def list_printers(self):
                return []

        with pytest.raises(TypeError):
            Incomplete()


class TestMockPrinterBackend:
    def test_list_printers_matches_registry(self):
        backend = MockPrinterBackend()
        assert backend.list_printers() == available_printers()

    def test_grayscale_flag_is_logged(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W", grayscale=True)
        assert backend.print_log[0]["grayscale"] is True

    def test_grayscale_defaults_to_false(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W")
        assert backend.print_log[0]["grayscale"] is False

    def test_borderless_flag_is_logged(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W", borderless=True)
        assert backend.print_log[0]["borderless"] is True

    def test_borderless_defaults_to_false(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W")
        assert backend.print_log[0]["borderless"] is False

    def test_page_range_is_logged(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W", page_range=[1, 3])
        assert backend.print_log[0]["page_range"] == [1, 3]

    def test_page_range_defaults_to_none(self):
        backend = MockPrinterBackend()
        backend.print_file("/a.pdf", "Brother DCP-T420W")
        assert backend.print_log[0]["page_range"] is None

    def test_print_file_logs_the_job_and_returns_a_job_id(self):
        backend = MockPrinterBackend()
        job_id = backend.print_file("/uploads/doc.pdf", "Brother DCP-T420W", copies=2)

        assert job_id
        assert len(backend.print_log) == 1
        entry = backend.print_log[0]
        assert entry["job_id"] == job_id
        assert entry["file_path"] == "/uploads/doc.pdf"
        assert entry["printer_name"] == "Brother DCP-T420W"
        assert entry["copies"] == 2

    def test_default_copies_is_one(self):
        backend = MockPrinterBackend()
        backend.print_file("/uploads/doc.pdf", "Brother DCP-T420W")
        assert backend.print_log[0]["copies"] == 1

    def test_successive_jobs_get_distinct_ids(self):
        backend = MockPrinterBackend()
        first = backend.print_file("/a.pdf", "Brother DCP-T420W")
        second = backend.print_file("/b.pdf", "Brother DCP-T420W")
        assert first != second
        assert len(backend.print_log) == 2

    def test_unknown_printer_rejected(self):
        backend = MockPrinterBackend()
        with pytest.raises(PrintError, match="unknown printer"):
            backend.print_file("/a.pdf", "Not A Real Printer")
        assert backend.print_log == []

    def test_zero_or_negative_copies_rejected(self):
        backend = MockPrinterBackend()
        with pytest.raises(PrintError, match="copies"):
            backend.print_file("/a.pdf", "Brother DCP-T420W", copies=0)
        assert backend.print_log == []

    def test_two_backend_instances_do_not_share_print_logs(self):
        a, b = MockPrinterBackend(), MockPrinterBackend()
        a.print_file("/a.pdf", "Brother DCP-T420W")
        assert a.print_log != []
        assert b.print_log == []
