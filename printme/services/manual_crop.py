"""Manual crop parsing for customer-supplied photo crops. Pure module -
no Flask/DB/image imports - so it's trivially unit-testable, mirroring
why page_range.py is kept pure.
"""

import json
import math

_REQUIRED_KEYS = ("x", "y", "w", "h")


def parse_crop_fractions(raw):
    """A customer-supplied manual crop, sent as JSON
    '{"x":.., "y":.., "w":.., "h":..}' - fractions (0-1) of the
    ORIGINAL photo's natural width/height. Returns an (x, y, w, h)
    float tuple, or None if `raw` is blank/missing/malformed/out of
    range. None must be treated by callers exactly like "no manual
    crop supplied" - never as an error to surface to the customer,
    mirroring routes/upload.py's _clamp_qty silent-default philosophy.

    No clamping happens here - anything outside range is rejected
    outright, since pixel-space clamping needs the real image
    dimensions, which this module deliberately doesn't know about.
    """
    if not raw or not str(raw).strip():
        return None

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    if not all(key in data for key in _REQUIRED_KEYS):
        return None

    try:
        x, y, w, h = (float(data[key]) for key in _REQUIRED_KEYS)
    except (TypeError, ValueError):
        return None

    # json.loads accepts bare NaN/Infinity tokens by default - reject
    # them explicitly rather than letting them silently pass range
    # checks below (e.g. `float("nan") <= 1` is False, but comparisons
    # involving NaN are unreliable enough not to trust implicitly).
    if not all(math.isfinite(v) for v in (x, y, w, h)):
        return None

    if not (0 <= x <= 1):
        return None
    if not (0 <= y <= 1):
        return None
    if not (0 < w <= 1):
        return None
    if not (0 < h <= 1):
        return None

    return (x, y, w, h)
