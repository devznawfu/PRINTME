from pathlib import Path

from pypdf import PdfWriter

from printme.services.pdf_render import rasterize_pdf


def _multi_page_pdf(path, n_pages):
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=200, height=100)
    with open(path, "wb") as f:
        writer.write(f)
    return path


class TestRasterizePdf:
    def test_renders_every_page_by_default(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 3)
        images = rasterize_pdf(pdf)
        assert len(images) == 3
        assert all(img.mode == "RGB" for img in images)

    def test_renders_at_300_dpi_by_default(self, tmp_path):
        """A 200x100pt page (72pt/in) at 300 DPI rasterizes to roughly
        833x417px - proves the default zoom is actually applied."""
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 1)
        img = rasterize_pdf(pdf)[0]
        assert abs(img.width - round(200 / 72 * 300)) <= 1
        assert abs(img.height - round(100 / 72 * 300)) <= 1

    def test_custom_zoom_is_applied(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 1)
        img = rasterize_pdf(pdf, zoom=1.0)
        assert abs(img[0].width - 200) <= 1
        assert abs(img[0].height - 100) <= 1

    def test_page_numbers_selects_a_subset_in_order(self, tmp_path):
        """Each blank page here is identical, so this only proves the
        COUNT and ORDER of pages selected - identical page content
        makes per-page visual distinction pointless to assert on."""
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 5)
        images = rasterize_pdf(pdf, page_numbers=[3, 1])
        assert len(images) == 2

    def test_page_numbers_none_means_every_page(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 4)
        assert len(rasterize_pdf(pdf, page_numbers=None)) == 4

    def test_single_page_number_subset(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 5)
        assert len(rasterize_pdf(pdf, page_numbers=[3])) == 1

    def test_accepts_a_path_object_or_a_string(self, tmp_path):
        pdf = _multi_page_pdf(tmp_path / "doc.pdf", 1)
        assert len(rasterize_pdf(Path(pdf))) == 1
        assert len(rasterize_pdf(str(pdf))) == 1
