from rectpack import MaxRectsBssf, PackingBin, PackingMode, SORT_AREA, newPacker

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


def pack(items: list[PhotoItem]) -> list[PackedSheet]:
    """Pack photo items onto the minimum number of A4 sheets at 300 DPI.

    Pure function: same input always produces the same output. Raises
    ValueError for an unknown size_name or a duplicate item_id - both are
    caller bugs, not data this module should silently paper over.
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

    packer = newPacker(
        mode=PackingMode.Offline,
        bin_algo=PackingBin.BFF,
        pack_algo=MaxRectsBssf,
        sort_algo=SORT_AREA,
        rotation=True,
    )
    packer.add_bin(USABLE_WIDTH_PX, USABLE_HEIGHT_PX, count=float("inf"))

    size_by_id = {item.item_id: item.size_name for item in items}
    for item in items:
        w, h = PHOTO_SIZES_PX[item.size_name]
        packer.add_rect(w + GUTTER_PX, h + GUTTER_PX, rid=item.item_id)

    packer.pack()

    sheets = []
    for sheet_index, bin_ in enumerate(packer):
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
