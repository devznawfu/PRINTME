import pytest
from PIL import Image

from printme.services.photo_erase import apply_erase, parse_strokes


class TestParseStrokes:
    def test_valid_single_stroke_parses(self):
        result = parse_strokes(
            '{"strokes": [[{"x": 0.1, "y": 0.2}, {"x": 0.3, "y": 0.4}]], "radius": 0.05}'
        )
        assert result == ([[(0.1, 0.2), (0.3, 0.4)]], 0.05)

    def test_multiple_strokes_parse(self):
        strokes, radius = parse_strokes(
            '{"strokes": [[{"x": 0.1, "y": 0.1}], [{"x": 0.9, "y": 0.9}]], "radius": 0.02}'
        )
        assert len(strokes) == 2
        assert radius == 0.02

    def test_none_returns_none(self):
        assert parse_strokes(None) is None

    def test_blank_string_returns_none(self):
        assert parse_strokes("") is None
        assert parse_strokes("   ") is None

    def test_malformed_json_returns_none(self):
        assert parse_strokes("{not valid json") is None

    def test_missing_strokes_key_returns_none(self):
        assert parse_strokes('{"radius": 0.05}') is None

    def test_missing_radius_key_returns_none(self):
        assert parse_strokes('{"strokes": [[{"x": 0.1, "y": 0.1}]]}') is None

    def test_empty_strokes_list_returns_none(self):
        assert parse_strokes('{"strokes": [], "radius": 0.05}') is None

    def test_empty_individual_stroke_returns_none(self):
        assert parse_strokes('{"strokes": [[]], "radius": 0.05}') is None

    def test_point_missing_x_or_y_returns_none(self):
        assert parse_strokes('{"strokes": [[{"x": 0.1}]], "radius": 0.05}') is None
        assert parse_strokes('{"strokes": [[{"y": 0.1}]], "radius": 0.05}') is None

    def test_non_numeric_point_returns_none(self):
        assert parse_strokes('{"strokes": [[{"x": "a", "y": 0.1}]], "radius": 0.05}') is None

    @pytest.mark.parametrize(
        "raw",
        [
            '{"strokes": [[{"x": NaN, "y": 0.1}]], "radius": 0.05}',
            '{"strokes": [[{"x": 0.1, "y": Infinity}]], "radius": 0.05}',
            '{"strokes": [[{"x": 0.1, "y": 0.1}]], "radius": NaN}',
        ],
    )
    def test_bare_nan_and_infinity_are_rejected(self, raw):
        assert parse_strokes(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            '{"strokes": [[{"x": -0.01, "y": 0.1}]], "radius": 0.05}',
            '{"strokes": [[{"x": 1.01, "y": 0.1}]], "radius": 0.05}',
            '{"strokes": [[{"x": 0.1, "y": -0.01}]], "radius": 0.05}',
            '{"strokes": [[{"x": 0.1, "y": 1.01}]], "radius": 0.05}',
        ],
    )
    def test_out_of_range_points_return_none(self, raw):
        assert parse_strokes(raw) is None

    def test_radius_out_of_range_returns_none(self):
        assert parse_strokes('{"strokes": [[{"x": 0.1, "y": 0.1}]], "radius": 0.0001}') is None
        assert parse_strokes('{"strokes": [[{"x": 0.1, "y": 0.1}]], "radius": 0.9}') is None

    def test_strokes_not_a_list_returns_none(self):
        assert parse_strokes('{"strokes": "nope", "radius": 0.05}') is None


class TestApplyErase:
    def test_painted_region_becomes_white(self):
        img = Image.new("RGB", (100, 100), (0, 0, 0))  # all black

        out = apply_erase(img, [[(0.5, 0.5)]], radius_fraction=0.1)

        assert out.getpixel((50, 50)) == (255, 255, 255)

    def test_untouched_region_is_unchanged(self):
        img = Image.new("RGB", (100, 100), (0, 0, 0))

        out = apply_erase(img, [[(0.1, 0.1)]], radius_fraction=0.02)

        assert out.getpixel((90, 90)) == (0, 0, 0)

    def test_returns_a_new_image_not_a_mutated_original(self):
        img = Image.new("RGB", (100, 100), (0, 0, 0))

        out = apply_erase(img, [[(0.5, 0.5)]], radius_fraction=0.1)

        assert img.getpixel((50, 50)) == (0, 0, 0)  # original untouched
        assert out is not img

    def test_multi_point_stroke_fills_the_line_between_points(self):
        img = Image.new("RGB", (100, 100), (0, 0, 0))

        out = apply_erase(img, [[(0.1, 0.5), (0.9, 0.5)]], radius_fraction=0.03)

        # A point on the line between the two stroke endpoints should
        # be painted, not just the endpoints themselves.
        assert out.getpixel((50, 50)) == (255, 255, 255)

    def test_multiple_strokes_all_apply(self):
        img = Image.new("RGB", (100, 100), (0, 0, 0))

        out = apply_erase(img, [[(0.1, 0.1)], [(0.9, 0.9)]], radius_fraction=0.05)

        assert out.getpixel((10, 10)) == (255, 255, 255)
        assert out.getpixel((90, 90)) == (255, 255, 255)

    def test_non_rgb_source_is_converted(self):
        img = Image.new("L", (50, 50), 0)  # grayscale

        out = apply_erase(img, [[(0.5, 0.5)]], radius_fraction=0.1)

        assert out.mode == "RGB"
