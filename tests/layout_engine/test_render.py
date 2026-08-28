from printme.layout_engine import sizes
from printme.layout_engine.packer import pack
from printme.layout_engine.render import render_sheet
from printme.layout_engine.types import PhotoItem


def test_render_of_sheet_with_no_items_has_no_grid_lines():
    from dataclasses import replace

    sheet = pack([PhotoItem("only", "1x1")])[0]
    empty_render = render_sheet(replace(sheet, items=()))
    assert empty_render.grid_lines == ()


def test_render_margins_and_usable_area_match_sizes_constants():
    sheets = pack([PhotoItem("only", "1x1")])
    render = render_sheet(sheets[0])

    assert render.sheet_width == sizes.A4_WIDTH_PX
    assert render.sheet_height == sizes.A4_HEIGHT_PX
    assert render.margin == sizes.SHEET_MARGIN_PX
    assert render.usable_x == sizes.SHEET_MARGIN_PX
    assert render.usable_y == sizes.SHEET_MARGIN_PX
    assert render.usable_width == sizes.USABLE_WIDTH_PX
    assert render.usable_height == sizes.USABLE_HEIGHT_PX


def test_render_usable_area_equals_full_sheet_when_margin_is_zero():
    """The shop owner's requirement, at the render level: the preview's
    usable-area box should span the whole sheet, not a margin-inset
    box."""
    sheets = pack([PhotoItem("only", "1x1")])
    render = render_sheet(sheets[0])

    assert render.usable_x == 0
    assert render.usable_y == 0
    assert render.usable_width == render.sheet_width
    assert render.usable_height == render.sheet_height


def test_render_emits_four_grid_lines_per_placed_item_matching_its_bounds():
    items = [PhotoItem(f"i{i}", "2x2") for i in range(3)]
    sheet = pack(items)[0]
    render = render_sheet(sheet)

    assert len(render.grid_lines) == 4 * len(sheet.items)

    for item in sheet.items:
        x1, y1 = item.x, item.y
        x2, y2 = item.x + item.width, item.y + item.height
        expected_edges = {
            (x1, y1, x2, y1),  # top
            (x1, y2, x2, y2),  # bottom
            (x1, y1, x1, y2),  # left
            (x2, y1, x2, y2),  # right
        }
        actual_edges = {(l.x1, l.y1, l.x2, l.y2) for l in render.grid_lines}
        assert expected_edges <= actual_edges
