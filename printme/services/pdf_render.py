"""Pure PDF page rasterization via PyMuPDF - no Flask/DB/win32 imports.
Shared by the win32 print backend (printing) and the admin document-
preview thumbnails (services/document_preview.py), so both go through
the same rendering code rather than two independent implementations.
"""

import pymupdf
from PIL import Image

# PDF page geometry is in points (1/72in); render at the same 300 DPI
# the rest of the pipeline uses (printme/layout_engine/sizes.py).
PDF_ZOOM_AT_300_DPI = 300 / 72


def zoom_for_dpi(dpi):
    """Points-to-pixels zoom factor for an arbitrary DPI - same 1/72in
    math as PDF_ZOOM_AT_300_DPI, generalized for admin print-quality
    presets (draft/normal/best - see models.job.PRINT_QUALITIES) that
    need a lower or higher rasterization resolution than the pipeline's
    normal 300 DPI default."""
    return dpi / 72


def rasterize_pdf(path, zoom=PDF_ZOOM_AT_300_DPI, page_numbers=None):
    """Every page of the PDF at `path` as an RGB PIL Image, rendered at
    `zoom`. `page_numbers`, if given, is a 1-indexed subset (e.g.
    [1, 3, 5]) - only those pages are rasterized, in the given order.
    None (default) rasterizes every page in document order."""
    doc = pymupdf.open(str(path))
    try:
        matrix = pymupdf.Matrix(zoom, zoom)
        pages = list(doc) if page_numbers is None else [doc[n - 1] for n in page_numbers]
        return [
            Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            for pix in (page.get_pixmap(matrix=matrix) for page in pages)
        ]
    finally:
        doc.close()
