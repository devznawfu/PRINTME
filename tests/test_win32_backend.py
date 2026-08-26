"""Tests for Win32PrinterBackend.

_images_for() is tested for real - PyMuPDF and Pillow are both
installed here, so PDF/PNG rasterization genuinely runs. The GDI
drawing side (_draw_images/print_file) can't be verified for real
without Windows (win32ui/win32con aren't installed on this Linux
container at all), so those are logic-only tests against
unittest.mock.MagicMock stand-ins - call sequencing, validation, and
error wrapping, NOT a claim that real printing works. Per the
printme-printing skill, real verification only happens on the actual
Windows admin PC.
"""

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pypdf import PdfWriter

from printme.services.printing.win32_backend import _images_for
from printme.services.printing.base import PrintError

FIXTURES = Path(__file__).parent / "fixtures"


def _multi_page_pdf_bytes(num_pages):
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestImagesFor:
    def test_png_returns_one_image_at_original_size(self, tmp_path):
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (40, 30), "white").save(path)

        images = _images_for(path)

        assert len(images) == 1
        assert images[0].size == (40, 30)
        assert images[0].mode == "RGB"

    def test_jpeg_uses_the_real_fixture(self):
        images = _images_for(FIXTURES / "face_one.jpg")
        assert len(images) == 1
        assert images[0].mode == "RGB"

    def test_single_page_pdf_returns_one_image(self, tmp_path):
        path = tmp_path / "doc.pdf"
        path.write_bytes(_multi_page_pdf_bytes(1))

        images = _images_for(path)

        assert len(images) == 1
        assert images[0].mode == "RGB"

    def test_multi_page_pdf_returns_one_image_per_page(self, tmp_path):
        path = tmp_path / "doc.pdf"
        path.write_bytes(_multi_page_pdf_bytes(3))

        images = _images_for(path)

        assert len(images) == 3

    def test_pdf_page_rendered_at_300_dpi(self, tmp_path):
        """A 200x100pt page (72pt/in) at 300 DPI should rasterize to
        roughly 833x417px - proves the zoom factor is actually applied,
        not just "some" image coming back."""
        path = tmp_path / "doc.pdf"
        path.write_bytes(_multi_page_pdf_bytes(1))

        img = _images_for(path)[0]

        assert abs(img.width - round(200 / 72 * 300)) <= 1
        assert abs(img.height - round(100 / 72 * 300)) <= 1


@pytest.fixture
def fake_pywin32(monkeypatch):
    fake_win32ui = MagicMock()
    fake_win32con = MagicMock()
    fake_hdc = fake_win32ui.CreateDC.return_value
    fake_hdc.GetDeviceCaps.return_value = 1000  # same for HORZRES/VERTRES - fine for these tests

    monkeypatch.setitem(sys.modules, "win32ui", fake_win32ui)
    monkeypatch.setitem(sys.modules, "win32con", fake_win32con)
    monkeypatch.delitem(sys.modules, "printme.services.printing.win32_backend", raising=False)

    import printme.services.printing.win32_backend as mod

    # ImageWin.Dib's constructor calls a Windows-only PIL C extension
    # (Image.core.display) that doesn't exist in a Linux Pillow build
    # at all - mocking win32ui/win32con alone isn't enough to make
    # _draw_images() runnable here.
    monkeypatch.setattr(mod.ImageWin, "Dib", MagicMock())

    yield fake_win32ui, fake_hdc


def _backend(fake_pywin32):
    from printme.services.printing.win32_backend import Win32PrinterBackend

    return Win32PrinterBackend()


class TestPrintFile:
    def test_draws_one_page_per_pdf_page_in_order(self, fake_pywin32, tmp_path):
        fake_win32ui, fake_hdc = fake_pywin32
        path = tmp_path / "doc.pdf"
        path.write_bytes(_multi_page_pdf_bytes(2))

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W", copies=1)

        fake_win32ui.CreateDC.assert_called_once()
        fake_hdc.CreatePrinterDC.assert_called_once_with("Brother DCP-T420W")
        fake_hdc.StartDoc.assert_called_once()
        assert fake_hdc.StartPage.call_count == 2
        assert fake_hdc.EndPage.call_count == 2
        fake_hdc.EndDoc.assert_called_once()
        fake_hdc.DeleteDC.assert_called_once()

    def test_copies_repeats_the_whole_startdoc_enddoc_cycle(self, fake_pywin32, tmp_path):
        _, fake_hdc = fake_pywin32
        path = tmp_path / "sheet.png"
        from PIL import Image

        Image.new("RGB", (10, 10), "white").save(path)

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W", copies=3)

        assert fake_hdc.StartDoc.call_count == 3
        assert fake_hdc.EndDoc.call_count == 3
        assert fake_hdc.StartPage.call_count == 3  # one page per copy, one image

    def test_returns_a_job_id(self, fake_pywin32, tmp_path):
        path = tmp_path / "sheet.png"
        from PIL import Image

        Image.new("RGB", (10, 10), "white").save(path)

        backend = _backend(fake_pywin32)
        job_id = backend.print_file(path, "Brother DCP-T420W")
        assert "Brother DCP-T420W" in job_id

    def test_unknown_printer_rejected_without_touching_the_device_context(self, fake_pywin32, tmp_path):
        fake_win32ui, _ = fake_pywin32
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="unknown printer"):
            backend.print_file(tmp_path / "x.png", "Not A Real Printer")
        fake_win32ui.CreateDC.assert_not_called()

    def test_zero_copies_rejected_without_touching_the_device_context(self, fake_pywin32, tmp_path):
        fake_win32ui, _ = fake_pywin32
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="copies"):
            backend.print_file(tmp_path / "x.png", "Brother DCP-T420W", copies=0)
        fake_win32ui.CreateDC.assert_not_called()

    def test_gdi_failure_is_wrapped_in_print_error(self, fake_pywin32, tmp_path):
        fake_win32ui, _ = fake_pywin32
        fake_win32ui.CreateDC.side_effect = OSError("no such device")
        path = tmp_path / "sheet.png"
        from PIL import Image

        Image.new("RGB", (10, 10), "white").save(path)

        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError, match="Brother DCP-T420W"):
            backend.print_file(path, "Brother DCP-T420W")

    def test_missing_file_is_wrapped_in_print_error(self, fake_pywin32, tmp_path):
        backend = _backend(fake_pywin32)
        with pytest.raises(PrintError):
            backend.print_file(tmp_path / "does-not-exist.png", "Brother DCP-T420W")


class TestListPrinters:
    def test_matches_registry(self, fake_pywin32):
        from printme.services.printing.printer_registry import available_printers

        backend = _backend(fake_pywin32)
        assert backend.list_printers() == available_printers()
