from dataclasses import dataclass

from printme.layout_engine.types import PackedSheet


@dataclass(frozen=True)
class Line:
    x1: int
    y1: int
    x2: int
    y2: int


@dataclass(frozen=True)
class SheetRender:
    """Plain-data drawing instructions for one packed sheet: the sheet
    outline, the margin/usable-area box, and one cutting-guide rectangle
    (4 lines) per placed item. No image library involved - turning this
    into an actual PNG is `services/photo_sheet_renderer.py`'s job."""

    sheet_width: int
    sheet_height: int
    margin: int
    usable_x: int
    usable_y: int
    usable_width: int
    usable_height: int
    grid_lines: tuple[Line, ...]


def render_sheet(sheet: PackedSheet) -> SheetRender:
    lines = []
    for item in sheet.items:
        x1, y1 = item.x, item.y
        x2, y2 = item.x + item.width, item.y + item.height
        lines.append(Line(x1, y1, x2, y1))  # top
        lines.append(Line(x1, y2, x2, y2))  # bottom
        lines.append(Line(x1, y1, x1, y2))  # left
        lines.append(Line(x2, y1, x2, y2))  # right

    return SheetRender(
        sheet_width=sheet.width,
        sheet_height=sheet.height,
        margin=sheet.margin,
        usable_x=sheet.margin,
        usable_y=sheet.margin,
        usable_width=sheet.width - 2 * sheet.margin,
        usable_height=sheet.height - 2 * sheet.margin,
        grid_lines=tuple(lines),
    )
