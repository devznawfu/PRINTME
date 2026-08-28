import pytest

from printme.services.manual_crop import parse_crop_fractions


class TestParseCropFractions:
    def test_valid_crop_parses(self):
        assert parse_crop_fractions('{"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.5}') == (
            0.1,
            0.2,
            0.5,
            0.5,
        )

    def test_full_image_boundary_is_accepted(self):
        assert parse_crop_fractions('{"x": 0, "y": 0, "w": 1, "h": 1}') == (0, 0, 1, 1)

    def test_none_returns_none(self):
        assert parse_crop_fractions(None) is None

    def test_blank_string_returns_none(self):
        assert parse_crop_fractions("") is None
        assert parse_crop_fractions("   ") is None

    def test_malformed_json_returns_none(self):
        assert parse_crop_fractions("{not valid json") is None

    def test_json_that_is_not_an_object_returns_none(self):
        assert parse_crop_fractions("[0.1, 0.2, 0.5, 0.5]") is None
        assert parse_crop_fractions("42") is None
        assert parse_crop_fractions('"hello"') is None

    @pytest.mark.parametrize(
        "raw",
        [
            '{"x": 0.1, "y": 0.2, "w": 0.5}',  # missing h
            '{"x": 0.1, "y": 0.2, "h": 0.5}',  # missing w
            '{"y": 0.2, "w": 0.5, "h": 0.5}',  # missing x
            '{"x": 0.1, "w": 0.5, "h": 0.5}',  # missing y
            "{}",
        ],
    )
    def test_missing_keys_return_none(self, raw):
        assert parse_crop_fractions(raw) is None

    def test_non_numeric_values_return_none(self):
        assert parse_crop_fractions('{"x": "a", "y": 0.2, "w": 0.5, "h": 0.5}') is None

    @pytest.mark.parametrize(
        "raw",
        [
            '{"x": NaN, "y": 0.2, "w": 0.5, "h": 0.5}',
            '{"x": 0.1, "y": Infinity, "w": 0.5, "h": 0.5}',
            '{"x": 0.1, "y": 0.2, "w": -Infinity, "h": 0.5}',
        ],
    )
    def test_bare_nan_and_infinity_json_tokens_are_rejected(self, raw):
        """Python's json.loads accepts bare NaN/Infinity by default -
        an easy footgun if not explicitly guarded against."""
        assert parse_crop_fractions(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            '{"x": -0.01, "y": 0.2, "w": 0.5, "h": 0.5}',
            '{"x": 1.01, "y": 0.2, "w": 0.5, "h": 0.5}',
            '{"x": 0.1, "y": -0.01, "w": 0.5, "h": 0.5}',
            '{"x": 0.1, "y": 1.01, "w": 0.5, "h": 0.5}',
            '{"x": 0.1, "y": 0.2, "w": 0, "h": 0.5}',
            '{"x": 0.1, "y": 0.2, "w": 1.01, "h": 0.5}',
            '{"x": 0.1, "y": 0.2, "w": 0.5, "h": 0}',
            '{"x": 0.1, "y": 0.2, "w": 0.5, "h": 1.01}',
        ],
    )
    def test_out_of_range_values_return_none(self, raw):
        assert parse_crop_fractions(raw) is None
