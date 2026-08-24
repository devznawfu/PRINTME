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
    ones = [PhotoItem(f"a{i}", "1x1") for i in range(75)]
    visas = [PhotoItem(f"b{i}", "Visa") for i in range(5)]

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


def test_packing_is_deterministic():
    items = (
        [PhotoItem(f"one{i}", "1x1") for i in range(12)]
        + [PhotoItem(f"pp{i}", "Passport") for i in range(9)]
    )
    first = pack(items)
    second = pack(items)
    assert first == second


def test_rotation_only_applies_to_non_square_sizes_and_swaps_dimensions():
    items = (
        [PhotoItem(f"pp{i}", "Passport") for i in range(40)]
        + [PhotoItem(f"one{i}", "1x1") for i in range(10)]
        + [PhotoItem(f"two{i}", "2x2") for i in range(10)]
        + [PhotoItem(f"visa{i}", "Visa") for i in range(10)]
    )
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


def test_unknown_size_name_raises():
    with pytest.raises(ValueError):
        pack([PhotoItem("x", "4x6")])


def test_duplicate_item_id_raises():
    with pytest.raises(ValueError):
        pack([PhotoItem("dup", "1x1"), PhotoItem("dup", "2x2")])
