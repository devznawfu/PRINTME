"""Document print-job page thumbnails, for the admin's print-
confirmation popup ("a preview of what will be printed"). Rendering
itself is pure (no Flask/DB) - the caching/serving lives in the route
(printme/routes/api.py), same split as pdf_render.py.
"""

from pathlib import Path

from PIL import Image

from printme.services.pdf_render import rasterize_pdf


def render_page_thumbnail(processed_path, page_number, out_path, max_dim=220):
    """A PNG thumbnail of one page (1-indexed) of `processed_path`,
    written to `out_path`. PDFs render via pdf_render.rasterize_pdf; a
    single-image document (JPG/PNG/JFIF) is just resized - it only
    ever has page 1, callers are expected to have already validated
    page_number against the job's real page count."""
    processed_path = Path(processed_path)
    if processed_path.suffix.lower() == ".pdf":
        img = rasterize_pdf(processed_path, page_numbers=[page_number])[0]
    else:
        with Image.open(processed_path) as opened:
            img = opened.convert("RGB")

    img.thumbnail((max_dim, max_dim))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path
