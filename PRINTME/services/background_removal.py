"""Background removal for the photo pipeline (rembg -> white background).

Offline note: rembg's model is fetched from the internet on first use
and cached locally (U2NET_HOME, default ~/.u2net) - this violates "no
internet dependency" if it happens on the shop PC at print time. The
model must be pre-cached once, with internet access, during setup
(e.g. by importing this module once before going offline); after that,
rembg reads the cached file and never reaches out again.
"""

import cv2
import numpy as np
from PIL import Image
from rembg import new_session, remove

WHITE_BACKGROUND = (255, 255, 255, 255)

_session = None


def _get_session():
    global _session
    if _session is None:
        _session = new_session("u2net")
    return _session


def remove_background(image, out_path):
    """Run rembg on `image`, composite onto a solid white background, and
    save the result (RGB, no alpha) to out_path.

    `image` is a path (str/Path) or an already-open PIL.Image - the
    photo pipeline passes an in-memory cropped image directly rather
    than round-tripping it through a temp file.

    Returns the alpha mask (2D numpy array, 0-255) rembg produced, for
    detect_artifacts() to inspect. Note: this must read rembg's RAW
    cutout (no bgcolor) - passing bgcolor to rembg directly bakes the
    background in and flattens alpha to fully opaque everywhere,
    destroying the exact signal detect_artifacts() needs.
    """
    if isinstance(image, Image.Image):
        cutout = remove(image, session=_get_session())
    else:
        with Image.open(image) as src:
            cutout = remove(src, session=_get_session())  # RGBA, real alpha mask

    alpha_channel = cutout.split()[-1]
    alpha = np.array(alpha_channel)

    white_bg = Image.new("RGB", cutout.size, WHITE_BACKGROUND[:3])
    white_bg.paste(cutout, mask=alpha_channel)
    white_bg.save(out_path)

    return alpha


def detect_artifacts(alpha, fragment_ratio=0.08, hole_ratio=0.03, min_component_area=64):
    """Heuristic check for background-removal artifacts on an alpha mask.

    `alpha` is a 2D array (0-255, higher = more foreground). Returns a
    list of specific, staff-facing reason strings - empty if none found.
    Two checks:
    - fragments: a second foreground blob comparable in size to the main
      one (background wrongly kept as foreground somewhere else in frame)
    - holes: a gap inside the main foreground blob (subject wrongly cut
      into, e.g. hair/ears clipped out)
    """
    mask = (alpha > 127).astype("uint8") * 255
    reasons = []

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA]  # skip label 0 (background)
    significant = areas[areas >= min_component_area]

    if len(significant) == 0:
        reasons.append(
            "Background removal left no clear subject - check the photo."
        )
        return reasons

    main_area = significant.max()
    other_area = significant.sum() - main_area
    if other_area / main_area > fragment_ratio:
        reasons.append(
            "Background removal left stray fragments in the photo - check before printing."
        )

    main_label = 1 + int(areas.argmax())
    main_mask = (labels == main_label).astype("uint8") * 255
    contours, hierarchy = cv2.findContours(
        main_mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE
    )
    if hierarchy is not None:
        hierarchy = hierarchy[0]
        hole_area = sum(
            cv2.contourArea(contours[i])
            for i, h in enumerate(hierarchy)
            if h[3] != -1  # has a parent -> this contour is a hole
        )
        if hole_area / main_area > hole_ratio:
            reasons.append(
                "Background removal cut into the subject - check before printing."
            )

    return reasons
