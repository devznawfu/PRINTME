from dataclasses import dataclass, field


@dataclass(frozen=True)
class PhotoItem:
    """One photo to place on a sheet. `item_id` must be unique within a
    single `pack()` call and is opaque to the layout engine - callers use
    it to trace a placement back to the owning Job/PhotoSheetItem row."""

    item_id: str
    size_name: str


@dataclass(frozen=True)
class PlacedItem:
    """A PhotoItem's final position on a sheet, in full-sheet pixel
    coordinates (origin at the sheet's top-left corner, margin already
    accounted for). `width`/`height` are the item's actual printed size -
    swapped from its declared size when `rotated` is True."""

    item_id: str
    size_name: str
    x: int
    y: int
    width: int
    height: int
    rotated: bool


@dataclass(frozen=True)
class PackedSheet:
    sheet_index: int
    width: int
    height: int
    margin: int
    items: tuple[PlacedItem, ...] = field(default_factory=tuple)
