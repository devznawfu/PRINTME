"""Bin-packing logic for the Smart Layout Engine (CLAUDE.md).

Uses a shelf-based algorithm (First-Fit Decreasing Height, tried across
several sort orders per pack() call, keeping whichever uses the fewest
sheets) rather than a general 2D bin packer (this module previously
used rectpack's MaxRects family). That's a deliberate physical
constraint, not a simplification: the shop needs to guillotine-cut a
partially-used sheet along one straight horizontal line and feed the
still-blank remainder back into the printer for the next batch - that
only works if every "row" of photos spans the full sheet width, so
whatever's left below the last row is always a clean, full-width
rectangle. A general 2D packer doesn't guarantee that at all: it can
(and did, on a real order) leave a tall, narrow, unusable column of
blank space running the full sheet height right next to a tightly
packed block, instead of a clean cuttable strip across the bottom.

Confirmed empirically to cost roughly 15% more sheets on average than
an unconstrained packer across varied realistic batches - an accepted,
deliberate trade-off for a real physical requirement, not something to
keep optimizing away.
"""

from printme.layout_engine.sizes import (
    A4_HEIGHT_PX,
    A4_WIDTH_PX,
    GUTTER_PX,
    PHOTO_SIZES_PX,
    SHEET_MARGIN_PX,
    USABLE_HEIGHT_PX,
    USABLE_WIDTH_PX,
)
from printme.layout_engine.types import PackedSheet, PhotoItem, PlacedItem


def _orientations(size_name):
    """(width, height) candidates for size_name, in pixels - just the
    one for a square size, both (natural and rotated) for a
    rectangular one."""
    w, h = PHOTO_SIZES_PX[size_name]
    return [(w, h)] if w == h else [(w, h), (h, w)]


# No single sort order wins for every item mix (confirmed empirically,
# the same finding that previously justified trying every rectpack
# algorithm/sort combination) - each is tried per pack() call and the
# tightest result kept.
_SORT_KEYS = {
    "height": lambda item: -min(h for _, h in _orientations(item.size_name)),
    "height_then_width": lambda item: (
        -min(h for _, h in _orientations(item.size_name)),
        -min(w for w, _ in _orientations(item.size_name)),
    ),
    "area": lambda item: -(PHOTO_SIZES_PX[item.size_name][0] * PHOTO_SIZES_PX[item.size_name][1]),
    "width": lambda item: -min(w for w, _ in _orientations(item.size_name)),
    "perimeter": lambda item: -2 * sum(PHOTO_SIZES_PX[item.size_name]),
}


def _pack_all_sheets(items, sort_key):
    """Shelf-pack `items` onto as many sheets as needed.

    Items are processed tallest-first (by `sort_key`); each tries every
    already-open shelf on the current sheet, in order, before a new
    shelf opens below the last one. Because later items are never
    taller than earlier ones, an already-open shelf is always tall
    enough for a later item - only its remaining width needs checking.
    Rotation is tried per item/per shelf as just another candidate
    orientation, not a separate pass.

    GUTTER_PX is inserted only BETWEEN adjacent items and BETWEEN
    shelves - never as trailing padding after the last item in a row
    or after the last shelf on a sheet. Padding every item/shelf
    unconditionally (this module's first attempt) wastes exactly one
    gutter's worth of space per row/column for no reason: e.g. four
    "2x2" prints side by side need 4*600 + 3*24(gutters between them)
    = 2472px, which fits USABLE_WIDTH_PX's 2480px - but padding every
    item's own slot by a trailing GUTTER_PX makes it look like 2496px
    is needed, wrongly forcing a 4th column onto a new row instead.

    Returns a list of sheets, each a list of
    (item, x, y, width, height, rotated) tuples.
    """
    remaining = sorted(items, key=sort_key)
    sheets = []
    while remaining:
        shelves = []  # dicts: y, height, cursor_x (next free x, gutter-inclusive)
        placed = []
        still_remaining = []
        for item in remaining:
            choice = None  # (shelf_index, x, w, h)
            for shelf_index, shelf in enumerate(shelves):
                for w, h in _orientations(item.size_name):
                    next_x = shelf["cursor_x"] + (GUTTER_PX if shelf["cursor_x"] > 0 else 0)
                    if next_x + w <= USABLE_WIDTH_PX and h <= shelf["height"]:
                        choice = (shelf_index, next_x, w, h)
                        break
                if choice is not None:
                    break

            if choice is None:
                for w, h in _orientations(item.size_name):
                    new_y = shelves[-1]["y"] + shelves[-1]["height"] + GUTTER_PX if shelves else 0
                    if new_y + h <= USABLE_HEIGHT_PX and w <= USABLE_WIDTH_PX:
                        shelves.append({"y": new_y, "height": h, "cursor_x": 0})
                        choice = (len(shelves) - 1, 0, w, h)
                        break

            if choice is None:
                still_remaining.append(item)
                continue

            shelf_index, x, w, h = choice
            shelf = shelves[shelf_index]
            rotated = (w, h) != PHOTO_SIZES_PX[item.size_name]
            placed.append((item, x, shelf["y"], w, h, rotated))
            shelf["cursor_x"] = x + w

        if not placed:
            # Every remaining item is individually too big for a fresh
            # sheet - a caller/sizes.py bug (a defined size bigger than
            # USABLE_WIDTH_PX/HEIGHT_PX), not real data this module
            # should silently drop.
            raise ValueError(f"item too large to fit on any sheet: {remaining[0].size_name!r}")

        sheets.append(placed)
        remaining = still_remaining
    return sheets


def _sheet_density(sheet):
    """Packed area as a fraction of that sheet's own tight bounding
    box (not the full sheet area - a batch too small to fill a whole
    sheet shouldn't score "badly" just for not having enough content)."""
    if not sheet:
        return 0.0
    item_area = sum(w * h for _, _, _, w, h, _rotated in sheet)
    max_x = max(x + w for _, x, _y, w, _h, _rotated in sheet)
    max_y = max(y + h for _, _x, y, _w, h, _rotated in sheet)
    bbox_area = max_x * max_y
    return (item_area / bbox_area) if bbox_area else 0.0


def _score(sheets):
    """Lower is better: fewest sheets first, then tightest average
    per-sheet density as a tiebreaker."""
    n_sheets = len(sheets)
    avg_density = (sum(_sheet_density(s) for s in sheets) / n_sheets) if n_sheets else 0.0
    return (n_sheets, -avg_density)


def pack(items: list[PhotoItem]) -> list[PackedSheet]:
    """Pack photo items onto the minimum number of A4 sheets at 300 DPI,
    keeping every row full-sheet-width so any unused space is always a
    clean, cuttable, reusable strip - never a gap that splits placed
    items apart.

    Pure function: same input always produces the same output (ties
    between equally-good sort orders always resolve to whichever is
    defined first in _SORT_KEYS, a fixed order). Raises ValueError for
    an unknown size_name or a duplicate item_id - both are caller bugs,
    not data this module should silently paper over.
    """
    if not items:
        return []

    seen_ids: set[str] = set()
    for item in items:
        if item.item_id in seen_ids:
            raise ValueError(f"duplicate item_id: {item.item_id!r}")
        seen_ids.add(item.item_id)
        if item.size_name not in PHOTO_SIZES_PX:
            raise ValueError(f"unknown size_name: {item.size_name!r}")

    best_sheets = None
    best_score = None
    for sort_key in _SORT_KEYS.values():
        candidate = _pack_all_sheets(items, sort_key)
        score = _score(candidate)
        if best_score is None or score < best_score:
            best_score = score
            best_sheets = candidate

    sheets = []
    for sheet_index, raw_sheet in enumerate(best_sheets):
        placed = tuple(
            PlacedItem(
                item_id=item.item_id,
                size_name=item.size_name,
                x=SHEET_MARGIN_PX + x,
                y=SHEET_MARGIN_PX + y,
                width=w,
                height=h,
                rotated=rotated,
            )
            for item, x, y, w, h, rotated in raw_sheet
        )
        sheets.append(
            PackedSheet(
                sheet_index=sheet_index,
                width=A4_WIDTH_PX,
                height=A4_HEIGHT_PX,
                margin=SHEET_MARGIN_PX,
                items=placed,
            )
        )
    return sheets
