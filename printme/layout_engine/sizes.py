"""Physical constants for the Smart Layout Engine.

No Flask/DB imports here — this module (and the rest of layout_engine/)
must stay a pure, framework-free unit. See CLAUDE.md's Smart Layout
Engine section.
"""

DPI = 300
MM_PER_INCH = 25.4


def mm_to_px(mm: float) -> int:
    return round(mm / MM_PER_INCH * DPI)


def in_to_px(inches: float) -> int:
    return round(inches * DPI)


# A4 sheet, full size
A4_WIDTH_PX = mm_to_px(210)
A4_HEIGHT_PX = mm_to_px(297)

# Sheet margin (all four sides) and the cutting gutter left between
# adjacent photos so a straight cut doesn't clip the neighboring print.
SHEET_MARGIN_PX = mm_to_px(5)
GUTTER_PX = mm_to_px(2)

USABLE_WIDTH_PX = A4_WIDTH_PX - 2 * SHEET_MARGIN_PX
USABLE_HEIGHT_PX = A4_HEIGHT_PX - 2 * SHEET_MARGIN_PX

# Fixed photo sizes (width_px, height_px) - Philippine photo-lab
# convention. Confirm with the shop owner if these need adjusting.
PHOTO_SIZES_PX = {
    "1x1": (in_to_px(1), in_to_px(1)),
    "2x2": (in_to_px(2), in_to_px(2)),
    "Passport": (mm_to_px(35), mm_to_px(45)),
    "Visa": (mm_to_px(45), mm_to_px(45)),
}
