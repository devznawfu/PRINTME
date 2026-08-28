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

from printme.services.printing.win32_backend import _images_for, _match_borderless_paper_id
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

    def test_grayscale_png_is_l_mode(self, tmp_path):
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (40, 30), "white").save(path)

        images = _images_for(path, grayscale=True)

        assert images[0].mode == "L"

    def test_grayscale_pdf_pages_are_l_mode(self, tmp_path):
        path = tmp_path / "doc.pdf"
        path.write_bytes(_multi_page_pdf_bytes(2))

        images = _images_for(path, grayscale=True)

        assert all(img.mode == "L" for img in images)

    def test_default_is_not_grayscale(self, tmp_path):
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (40, 30), "white").save(path)

        assert _images_for(path)[0].mode == "RGB"


class TestMatchBorderlessPaperId:
    """Pure function over plain lists - no win32 module needed at all,
    unlike everything else in this file."""

    def test_matches_a_borderless_entry_case_insensitively(self):
        ids = [1, 9, 274]
        names = ["Letter", "A4 (210 x 297 mm)", "A4 (Borderless) (210 x 297 mm)"]
        assert _match_borderless_paper_id(ids, names) == 274

    def test_plain_a4_without_borderless_does_not_match(self):
        ids = [9]
        names = ["A4 (210 x 297 mm)"]
        assert _match_borderless_paper_id(ids, names) is None

    def test_edge_substring_false_positive_does_not_match(self):
        """Regression coverage for the exact false positive the real
        diagnostic script hit: "Ledger" and "A5 Long Edge" both contain
        "edge" as a substring, but neither is a real borderless entry -
        this function only ever matched on "borderless" itself."""
        ids = [3, 61]
        names = ["Ledger (279.4 x 431.8 mm)", "A5 Long Edge"]
        assert _match_borderless_paper_id(ids, names) is None

    def test_empty_lists_return_none(self):
        assert _match_borderless_paper_id([], []) is None

    def test_borderless_entry_for_a_different_size_is_ignored(self):
        ids = [280]
        names = ["10 x 15 cm (Borderless) (4 x 6 in)"]
        assert _match_borderless_paper_id(ids, names, target_size_name="a4") is None


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

    def test_grayscale_flag_reaches_the_drawn_image(self, fake_pywin32, tmp_path):
        import printme.services.printing.win32_backend as mod

        path = tmp_path / "sheet.png"
        from PIL import Image

        Image.new("RGB", (10, 10), "white").save(path)

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W", grayscale=True)

        drawn_image = mod.ImageWin.Dib.call_args[0][0]
        assert drawn_image.mode == "L"

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

    def test_borderless_uses_cover_scale_when_setup_succeeds(self, fake_pywin32, tmp_path, monkeypatch):
        """_borderless_dc's real DEVMODE/CreateDC dance can't be tested
        here (win32 isn't installed on Linux) - this monkeypatches it
        directly to prove _draw_images reacts correctly when it DOES
        succeed: skip the default DC entirely, and scale by the LARGER
        ratio (cover, not contain) so both edges get fully covered."""
        import win32con

        import printme.services.printing.win32_backend as mod
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (100, 50), "white").save(path)

        fake_borderless_hdc = MagicMock()
        fake_borderless_hdc.GetDeviceCaps.side_effect = (
            lambda cap: 200 if cap is win32con.HORZRES else 60
        )
        monkeypatch.setattr(mod, "_borderless_dc", lambda printer_name: fake_borderless_hdc)

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W", borderless=True)

        fake_win32ui, _ = fake_pywin32
        fake_win32ui.CreateDC.assert_not_called()
        fake_borderless_hdc.StartDoc.assert_called_once()
        draw_rect = mod.ImageWin.Dib.return_value.draw.call_args[0][1]
        # cover scale = max(200/100, 60/50) = 2.0 -> 200x100 (overflows
        # the 60px page height, which GDI/the printer clips for real)
        assert draw_rect[2] - draw_rect[0] == 200
        assert draw_rect[3] - draw_rect[1] == 100

    def test_borderless_falls_back_to_normal_dc_and_contain_scale_on_setup_failure(
        self, fake_pywin32, tmp_path, monkeypatch
    ):
        """A failed borderless setup must fall back to today's exact
        CreateDC()+CreatePrinterDC() path and today's contain scaling -
        never cover-crop math against the normal (smaller) printable
        area, which would wrongly crop real content."""
        import win32con

        import printme.services.printing.win32_backend as mod
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (100, 50), "white").save(path)

        fake_win32ui, fake_hdc = fake_pywin32
        fake_hdc.GetDeviceCaps.side_effect = lambda cap: 200 if cap is win32con.HORZRES else 60
        monkeypatch.setattr(mod, "_borderless_dc", lambda printer_name: None)

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W", borderless=True)

        fake_win32ui.CreateDC.assert_called_once()
        fake_hdc.CreatePrinterDC.assert_called_once_with("Brother DCP-T420W")
        draw_rect = mod.ImageWin.Dib.return_value.draw.call_args[0][1]
        # contain scale = min(200/100, 60/50) = 1.2 -> 120x60
        assert draw_rect[2] - draw_rect[0] == 120
        assert draw_rect[3] - draw_rect[1] == 60

    def test_borderless_not_requested_never_calls_borderless_dc(self, fake_pywin32, tmp_path, monkeypatch):
        import printme.services.printing.win32_backend as mod
        from PIL import Image

        path = tmp_path / "sheet.png"
        Image.new("RGB", (10, 10), "white").save(path)

        called = []
        monkeypatch.setattr(mod, "_borderless_dc", lambda printer_name: called.append(printer_name))

        backend = _backend(fake_pywin32)
        backend.print_file(path, "Brother DCP-T420W")

        assert called == []


class TestListPrinters:
    def test_matches_registry(self, fake_pywin32):
        from printme.services.printing.printer_registry import available_printers

        backend = _backend(fake_pywin32)
        assert backend.list_printers() == available_printers()
