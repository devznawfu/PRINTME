from printme.layout_engine import sizes


def test_in_to_px_at_300_dpi():
    assert sizes.in_to_px(1) == 300
    assert sizes.in_to_px(2) == 600


def test_mm_to_px_rounds_to_nearest_pixel():
    assert sizes.mm_to_px(210) == 2480
    assert sizes.mm_to_px(297) == 3508


def test_usable_area_equals_full_sheet_with_zero_margin():
    """The shop owner's requirement: a packed sheet uses the entire
    glossy sheet, no reserved margin - only GUTTER_PX between photos."""
    assert sizes.SHEET_MARGIN_PX == 0
    assert sizes.USABLE_WIDTH_PX == sizes.A4_WIDTH_PX
    assert sizes.USABLE_HEIGHT_PX == sizes.A4_HEIGHT_PX


def test_every_fixed_photo_size_fits_within_usable_area():
    for name, (w, h) in sizes.PHOTO_SIZES_PX.items():
        assert w <= sizes.USABLE_WIDTH_PX, name
        assert h <= sizes.USABLE_HEIGHT_PX, name


def test_all_required_sizes_are_defined():
    assert set(sizes.PHOTO_SIZES_PX) == {
        "1x1",
        "2x2",
        "Passport",
        "Visa",
        "Wallet",
        "4x6",
        "5x7",
        "4x4",
    }


def test_oversized_sizes_that_do_not_fit_a4_are_excluded():
    """8x8/8x10 were deliberately dropped per CLAUDE.md's explicit scope
    decision (no large-format printer hardware) - independent of
    USABLE_WIDTH_PX, which no longer subtracts a margin. Documented here
    so a future edit doesn't silently reintroduce a size that isn't
    actually supported by the shop's hardware."""
    assert "8x8" not in sizes.PHOTO_SIZES_PX
    assert "8x10" not in sizes.PHOTO_SIZES_PX
