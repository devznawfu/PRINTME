from printme.layout_engine import sizes


def test_in_to_px_at_300_dpi():
    assert sizes.in_to_px(1) == 300
    assert sizes.in_to_px(2) == 600


def test_mm_to_px_rounds_to_nearest_pixel():
    assert sizes.mm_to_px(210) == 2480
    assert sizes.mm_to_px(297) == 3508


def test_usable_area_is_smaller_than_full_sheet():
    assert sizes.USABLE_WIDTH_PX < sizes.A4_WIDTH_PX
    assert sizes.USABLE_HEIGHT_PX < sizes.A4_HEIGHT_PX
    assert sizes.USABLE_WIDTH_PX == sizes.A4_WIDTH_PX - 2 * sizes.SHEET_MARGIN_PX
    assert sizes.USABLE_HEIGHT_PX == sizes.A4_HEIGHT_PX - 2 * sizes.SHEET_MARGIN_PX


def test_every_fixed_photo_size_fits_within_usable_area():
    for name, (w, h) in sizes.PHOTO_SIZES_PX.items():
        assert w <= sizes.USABLE_WIDTH_PX, name
        assert h <= sizes.USABLE_HEIGHT_PX, name


def test_all_four_required_sizes_are_defined():
    assert set(sizes.PHOTO_SIZES_PX) == {"1x1", "2x2", "Passport", "Visa"}
