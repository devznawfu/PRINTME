import random

import pytest

from printme.layout_engine import sizes
from printme.layout_engine.packer import pack
from printme.layout_engine.types import PhotoItem


def _assert_no_overlaps_and_in_bounds(sheet):
    min_x, min_y = sheet.margin, sheet.margin
    max_x, max_y = sheet.width - sheet.margin, sheet.height - sheet.margin

    for item in sheet.items:
        assert item.x >= min_x
        assert item.y >= min_y
        assert item.x + item.width <= max_x
        assert item.y + item.height <= max_y

    items = list(sheet.items)
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            overlap = (
                a.x < b.x + b.width
                and b.x < a.x + a.width
                and a.y < b.y + b.height
                and b.y < a.y + a.height
            )
            assert not overlap, f"{a.item_id} overlaps {b.item_id}"


def _assert_forms_clean_full_width_shelves(sheet):
    """The physical requirement this packer exists to satisfy: every
    row of photos ("shelf") spans consistently without a later shelf
    overlapping an earlier one, so a straight horizontal guillotine cut
    below the last used shelf always leaves a clean, blank, full-width
    strip that can be fed back into the printer - never a gap that
    splits placed items apart mid-sheet."""
    rows = {}
    for item in sheet.items:
        rows.setdefault(item.y, []).append(item)

    ordered_ys = sorted(rows)
    prev_bottom = 0
    for y in ordered_ys:
        assert y >= prev_bottom, f"shelf at y={y} overlaps the previous shelf (ends at {prev_bottom})"
        row_items = rows[y]
        assert all(it.y == y for it in row_items)
        prev_bottom = y + max(it.height for it in row_items)


def test_empty_input_returns_no_sheets():
    assert pack([]) == []


@pytest.mark.parametrize("size_name", ["1x1", "2x2", "Passport", "Visa"])
def test_single_item_of_each_size_yields_one_correctly_placed_sheet(size_name):
    sheets = pack([PhotoItem("only", size_name)])

    assert len(sheets) == 1
    sheet = sheets[0]
    assert len(sheet.items) == 1
    placed = sheet.items[0]
    assert placed.item_id == "only"
    declared_w, declared_h = sizes.PHOTO_SIZES_PX[size_name]
    assert {placed.width, placed.height} == {declared_w, declared_h}
    _assert_no_overlaps_and_in_bounds(sheet)


def test_uniform_grid_fills_to_exact_computed_capacity():
    padded = sizes.PHOTO_SIZES_PX["1x1"][0] + sizes.GUTTER_PX
    cols = sizes.USABLE_WIDTH_PX // padded
    rows = sizes.USABLE_HEIGHT_PX // padded
    capacity = cols * rows

    exact = [PhotoItem(f"i{i}", "1x1") for i in range(capacity)]
    sheets = pack(exact)
    assert len(sheets) == 1
    assert len(sheets[0].items) == capacity
    _assert_no_overlaps_and_in_bounds(sheets[0])

    one_more = [PhotoItem(f"i{i}", "1x1") for i in range(capacity + 1)]
    overflowed = pack(one_more)
    assert len(overflowed) == 2
    assert len(overflowed[0].items) == capacity
    assert len(overflowed[1].items) == 1


def test_mixed_sizes_use_no_more_sheets_than_the_naive_separate_baseline():
    """75/5 no longer shows a STRICT improvement now that packing is
    tighter (zero gutter) - both approaches tie at 2 sheets, which is
    itself a sign packing improved, not a regression. 90/2 still shows
    real synergy from mixing (3 sheets separately, 2 mixed)."""
    ones = [PhotoItem(f"a{i}", "1x1") for i in range(90)]
    visas = [PhotoItem(f"b{i}", "Visa") for i in range(2)]

    ones_alone = pack(ones)
    visas_alone = pack(visas)
    naive_baseline = len(ones_alone) + len(visas_alone)

    mixed = pack(ones + visas)

    assert len(mixed) <= naive_baseline
    assert len(mixed) < naive_baseline, "expected mixing to beat the naive baseline here"


def test_overflow_places_every_item_exactly_once_with_no_drops_or_duplicates():
    items = [PhotoItem(f"i{i}", "1x1") for i in range(140)]
    sheets = pack(items)

    assert len(sheets) >= 2
    placed_ids = [placed.item_id for sheet in sheets for placed in sheet.items]
    assert sorted(placed_ids) == sorted(item.item_id for item in items)
    assert len(placed_ids) == len(set(placed_ids))


def test_no_overlaps_and_in_bounds_for_a_realistic_mixed_batch():
    items = (
        [PhotoItem(f"one{i}", "1x1") for i in range(10)]
        + [PhotoItem(f"two{i}", "2x2") for i in range(8)]
        + [PhotoItem(f"pp{i}", "Passport") for i in range(6)]
        + [PhotoItem(f"visa{i}", "Visa") for i in range(4)]
    )
    for sheet in pack(items):
        _assert_no_overlaps_and_in_bounds(sheet)
        _assert_forms_clean_full_width_shelves(sheet)


def test_packing_is_deterministic():
    items = (
        [PhotoItem(f"one{i}", "1x1") for i in range(12)]
        + [PhotoItem(f"pp{i}", "Passport") for i in range(9)]
    )
    first = pack(items)
    second = pack(items)
    assert first == second


def test_rotation_only_applies_to_non_square_sizes_and_swaps_dimensions():
    """A batch mixing every fixed size (found empirically to reliably
    make the winning sort order rotate at least one Passport/4x6 - a
    shorter shelf, opened by a smaller item, being reused for a taller
    non-square item that only fits sideways). Targets the rotation
    swap bookkeeping itself; not every batch needs rotation to pack
    well (a tighter unrotated grid often scores better, which is fine)."""
    counts = {
        "2x2": 17,
        "Visa": 15,
        "4x4": 12,
        "Wallet": 9,
        "5x7": 6,
        "4x6": 6,
        "Passport": 5,
        "1x1": 4,
    }
    items = [
        PhotoItem(f"{size_name}-{i}", size_name)
        for size_name, qty in counts.items()
        for i in range(qty)
    ]
    sheets = pack(items)

    saw_rotated_passport = False
    for sheet in sheets:
        for placed in sheet.items:
            declared_w, declared_h = sizes.PHOTO_SIZES_PX[placed.size_name]
            if placed.rotated:
                assert declared_w != declared_h, "only non-square sizes should ever rotate"
                assert (placed.width, placed.height) == (declared_h, declared_w)
                if placed.size_name == "Passport":
                    saw_rotated_passport = True
            else:
                assert (placed.width, placed.height) == (declared_w, declared_h)

    assert saw_rotated_passport, "expected at least one rotated Passport in this batch"


def test_zero_margin_lets_a_full_grid_start_flush_at_the_sheet_origin():
    """The shop owner's requirement: no reserved sheet margin - a
    packed item can legally sit flush at the physical sheet edge."""
    padded = sizes.PHOTO_SIZES_PX["1x1"][0] + sizes.GUTTER_PX
    cols = sizes.USABLE_WIDTH_PX // padded
    rows = sizes.USABLE_HEIGHT_PX // padded
    capacity = cols * rows

    items = [PhotoItem(f"i{i}", "1x1") for i in range(capacity)]
    sheets = pack(items)

    assert len(sheets) == 1
    sheet = sheets[0]
    assert min(item.x for item in sheet.items) == 0
    assert min(item.y for item in sheet.items) == 0


def test_sheet_margin_is_zero_on_every_packed_sheet():
    items = [PhotoItem(f"one{i}", "1x1") for i in range(140)]
    sheets = pack(items)

    assert len(sheets) >= 2
    for sheet in sheets:
        assert sheet.margin == 0


def test_real_world_regression_ten_1x1_and_ten_2x2_pack_tightly():
    """Regression test for a real customer order (10x "1x1" + 10x
    "2x2") that a general 2D packer (this module's previous approach)
    laid out as a tall, narrow column occupying only the left ~5.2in
    of the 8.27in-wide sheet, leaving a full-height blank strip on the
    right unusable for anything - not the clean, full-width leftover
    the shop needs to guillotine-cut and feed back into the printer.
    The shelf packer keeps every row spanning left-to-right so that
    invariant holds structurally, checked here directly."""
    items = [PhotoItem(f"one{i}", "1x1") for i in range(10)] + [
        PhotoItem(f"two{i}", "2x2") for i in range(10)
    ]
    sheets = pack(items)

    assert len(sheets) == 1
    sheet = sheets[0]
    _assert_forms_clean_full_width_shelves(sheet)

    # Fully-packed rows (four 2x2s each, see the dedicated gutter test
    # below) should use nearly the whole sheet width, not collapse
    # into a narrow column.
    max_x = max(item.x + item.width for item in sheet.items)
    assert max_x > 0.85 * sizes.USABLE_WIDTH_PX, (
        f"expected rows to span most of the sheet width, widest row only reached {max_x}px"
        f" of {sizes.USABLE_WIDTH_PX}px usable"
    )


def test_gutter_is_only_a_separator_not_trailing_padding_per_item():
    """GUTTER_PX is 0 today (the shop owner later asked for zero
    whitespace at all, not even a cutting gutter - see sizes.py), but
    this test still guards the underlying placement logic: gutter is
    only ever inserted BETWEEN items, never as trailing padding after
    the last one in a row. With a real nonzero gutter this made the
    difference between four "2x2" prints fitting in one row
    (4*600 + 3*gutter) or wrongly spilling a 4th onto a new row
    (4*(600+gutter)) - this module's first attempt at the shelf packer
    got that wrong. Still worth guarding even at gutter=0, in case a
    future paper type ever needs a nonzero one again."""
    items = [PhotoItem(f"two{i}", "2x2") for i in range(4)]
    sheets = pack(items)

    assert len(sheets) == 1
    ys = {item.y for item in sheets[0].items}
    assert ys == {0}, "expected all four 2x2 prints to land in a single row"


def test_clean_full_width_shelves_hold_across_many_randomized_real_size_batches():
    """This is the actual guarantee against future orders, not just the
    one real batch the other tests above are anchored to: the shelf
    invariant is a structural property of how pack() places items (a
    new shelf only ever opens below the last one, never beside it) -
    it can't depend on which specific sizes/quantities show up. Proven
    here across many different randomized combinations of every real
    fixed size, at randomized customer/row/quantity shapes, with a
    fixed seed so a real failure here is always reproducible."""
    rng = random.Random(20260828)
    size_names = list(sizes.PHOTO_SIZES_PX)

    for _ in range(50):
        items = []
        item_id = 0
        for _customer in range(rng.randint(1, 8)):
            for _row in range(rng.randint(1, 4)):
                size_name = rng.choice(size_names)
                for _ in range(rng.randint(1, 10)):
                    items.append(PhotoItem(f"i{item_id}", size_name))
                    item_id += 1

        sheets = pack(items)

        placed_ids = [it.item_id for sheet in sheets for it in sheet.items]
        assert sorted(placed_ids) == sorted(it.item_id for it in items)

        for sheet in sheets:
            _assert_no_overlaps_and_in_bounds(sheet)
            _assert_forms_clean_full_width_shelves(sheet)


def test_unknown_size_name_raises():
    with pytest.raises(ValueError):
        pack([PhotoItem("x", "9x9")])


def test_duplicate_item_id_raises():
    with pytest.raises(ValueError):
        pack([PhotoItem("dup", "1x1"), PhotoItem("dup", "2x2")])
