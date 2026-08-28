from rectpack import (
    SORT_AREA,
    SORT_DIFF,
    SORT_LSIDE,
    SORT_NONE,
    SORT_PERI,
    SORT_RATIO,
    SORT_SSIDE,
    MaxRectsBaf,
    MaxRectsBl,
    MaxRectsBlsf,
    MaxRectsBssf,
    PackingBin,
    PackingMode,
    newPacker,
)

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

# No single (pack_algo, sort_algo) combination wins for every item mix -
# confirmed empirically: the previous fixed choice (MaxRectsBssf,
# SORT_AREA) filled only 65% of its bounding box for a real 10x"1x1" +
# 10x"2x2" order (leaving one whole side of the sheet visibly empty),
# while MaxRectsBlsf/SORT_RATIO hit 97% on that same order - but was
# the WORST combination (worse than today's default) on a broader set
# of randomized multi-size batches. Rather than gamble on one heuristic,
# every combination is tried per pack() call and the tightest result
# wins - measured in milliseconds even for hundreds of items, so this
# is cheap enough to always do rather than guess which heuristic suits
# a given batch.
_PACK_ALGOS = (MaxRectsBaf, MaxRectsBl, MaxRectsBlsf, MaxRectsBssf)
_SORT_ALGOS = (SORT_AREA, SORT_NONE, SORT_LSIDE, SORT_SSIDE, SORT_RATIO, SORT_PERI, SORT_DIFF)


def _pack_with(items, pack_algo, sort_algo):
    packer = newPacker(
        mode=PackingMode.Offline,
        bin_algo=PackingBin.BFF,
        pack_algo=pack_algo,
        sort_algo=sort_algo,
        rotation=True,
    )
    packer.add_bin(USABLE_WIDTH_PX, USABLE_HEIGHT_PX, count=float("inf"))
    for item in items:
        w, h = PHOTO_SIZES_PX[item.size_name]
        packer.add_rect(w + GUTTER_PX, h + GUTTER_PX, rid=item.item_id)
    packer.pack()
    return packer


def _score(packer):
    """Lower is better: fewest sheets first, then tightest packing as a
    tiebreaker (negated so both terms sort the same direction).

    Density is measured against each sheet's own tight bounding box
    (the smallest rectangle containing everything actually placed on
    it), not the full USABLE_WIDTH_PX x USABLE_HEIGHT_PX sheet area -
    a batch that doesn't contain enough items to fill a whole sheet
    would always score "badly" against the full sheet area regardless
    of how tightly it's actually clustered, which doesn't capture the
    real complaint (a big rectangular void splitting otherwise-tight
    placements apart, not "the sheet has spare capacity left over" -
    that's expected and fine)."""
    bins = list(packer)
    n_sheets = len(bins)
    item_area = 0
    bbox_area = 0
    for bin_ in bins:
        if not bin_:
            continue
        item_area += sum(rect.width * rect.height for rect in bin_)
        max_x = max(rect.x + rect.width for rect in bin_)
        max_y = max(rect.y + rect.height for rect in bin_)
        bbox_area += max_x * max_y
    density = (item_area / bbox_area) if bbox_area else 0.0
    return (n_sheets, -density)


def pack(items: list[PhotoItem]) -> list[PackedSheet]:
    """Pack photo items onto the minimum number of A4 sheets at 300 DPI,
    as tightly as possible.

    Pure function: same input always produces the same output (ties
    between equally-good combinations always resolve to whichever comes
    first in _PACK_ALGOS/_SORT_ALGOS, a fixed order). Raises ValueError
    for an unknown size_name or a duplicate item_id - both are caller
    bugs, not data this module should silently paper over.
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

    best_packer = None
    best_score = None
    for pack_algo in _PACK_ALGOS:
        for sort_algo in _SORT_ALGOS:
            candidate = _pack_with(items, pack_algo, sort_algo)
            score = _score(candidate)
            if best_score is None or score < best_score:
                best_score = score
                best_packer = candidate

    size_by_id = {item.item_id: item.size_name for item in items}

    sheets = []
    for sheet_index, bin_ in enumerate(best_packer):
        placed = []
        for rect in bin_:
            size_name = size_by_id[rect.rid]
            orig_w, orig_h = PHOTO_SIZES_PX[size_name]
            rotated = (rect.width, rect.height) != (orig_w + GUTTER_PX, orig_h + GUTTER_PX)
            final_w, final_h = (orig_h, orig_w) if rotated else (orig_w, orig_h)
            placed.append(
                PlacedItem(
                    item_id=rect.rid,
                    size_name=size_name,
                    x=SHEET_MARGIN_PX + rect.x,
                    y=SHEET_MARGIN_PX + rect.y,
                    width=final_w,
                    height=final_h,
                    rotated=rotated,
                )
            )
        sheets.append(
            PackedSheet(
                sheet_index=sheet_index,
                width=A4_WIDTH_PX,
                height=A4_HEIGHT_PX,
                margin=SHEET_MARGIN_PX,
                items=tuple(placed),
            )
        )
    return sheets
