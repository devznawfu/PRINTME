"""Manual "snip"/erase for admin-reviewed photos: paints over an
unwanted region (a leftover background-removal artifact, a stray
object the automatic crop caught) directly on the already-processed
photo. Pure module (no Flask/DB/image-file-IO beyond PIL objects
passed in) - mirrors manual_crop.py's split, the route
(admin_review.py) owns loading/saving the actual file.

Fills with plain white, not a smart inpaint - CLAUDE.md's photo
pipeline already ends with "white background applied," so an erased
region matches the same background the rest of the photo already has.
"""

import json
import math

from PIL import Image, ImageDraw

FILL_COLOR = (255, 255, 255)
_MIN_RADIUS_FRACTION = 0.005
_MAX_RADIUS_FRACTION = 0.25


def parse_strokes(raw):
    """Admin-drawn erase strokes, sent as JSON
    '{"strokes": [[{"x":.., "y":..}, ...], ...], "radius": ..}' -
    `strokes` is a list of brush strokes, each a list of points as
    fractions (0-1) of the processed photo's natural width/height;
    `radius` is the brush radius as a fraction of the photo's width, so
    brush size scales correctly regardless of the photo's actual pixel
    dimensions. Returns (strokes, radius) - strokes as a list of
    (x, y) float-tuple lists - or None if `raw` is blank/missing/
    malformed/out of range. None means "nothing to erase," never an
    error to surface to staff, same philosophy as
    manual_crop.parse_crop_fractions."""
    if not raw or not str(raw).strip():
        return None

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    if "strokes" not in data or "radius" not in data:
        return None

    raw_strokes = data["strokes"]
    if not isinstance(raw_strokes, list) or not raw_strokes:
        return None

    try:
        radius = float(data["radius"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(radius) or not (_MIN_RADIUS_FRACTION <= radius <= _MAX_RADIUS_FRACTION):
        return None

    strokes = []
    for raw_stroke in raw_strokes:
        if not isinstance(raw_stroke, list) or not raw_stroke:
            return None
        points = []
        for point in raw_stroke:
            if not isinstance(point, dict) or "x" not in point or "y" not in point:
                return None
            try:
                x, y = float(point["x"]), float(point["y"])
            except (TypeError, ValueError):
                return None
            if not (math.isfinite(x) and math.isfinite(y)):
                return None
            if not (0 <= x <= 1 and 0 <= y <= 1):
                return None
            points.append((x, y))
        strokes.append(points)

    return strokes, radius


def apply_erase(image, strokes, radius_fraction):
    """A NEW PIL Image (RGB) - `image` with `strokes` painted over it in
    FILL_COLOR. Each point in each stroke is drawn as a filled circle,
    with consecutive points in the same stroke also connected by a
    thick line, so a fast brush drag doesn't leave gaps between the
    individual points a pointermove handler happened to sample."""
    out = image.convert("RGB").copy()
    draw = ImageDraw.Draw(out)
    width, height = out.size
    radius = max(1, round(radius_fraction * width))

    for stroke in strokes:
        pixels = [(round(x * width), round(y * height)) for x, y in stroke]
        for x, y in pixels:
            draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=FILL_COLOR)
        if len(pixels) > 1:
            draw.line(pixels, fill=FILL_COLOR, width=radius * 2)

    return out
