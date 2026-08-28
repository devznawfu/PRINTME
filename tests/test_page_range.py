import pytest

from printme.services.page_range import PageRangeError, describe_page_range, parse_page_range


class TestParsePageRange:
    def test_blank_spec_means_every_page(self):
        assert parse_page_range("", 5) == [1, 2, 3, 4, 5]

    def test_none_spec_means_every_page(self):
        assert parse_page_range(None, 3) == [1, 2, 3]

    def test_whitespace_only_spec_means_every_page(self):
        assert parse_page_range("   ", 3) == [1, 2, 3]

    def test_single_page(self):
        assert parse_page_range("3", 5) == [3]

    def test_simple_range(self):
        assert parse_page_range("1-3", 5) == [1, 2, 3]

    def test_mixed_pages_and_ranges(self):
        assert parse_page_range("1-3,5,7-9", 10) == [1, 2, 3, 5, 7, 8, 9]

    def test_tolerates_whitespace_around_tokens(self):
        assert parse_page_range(" 1 - 3 , 5 ", 5) == [1, 2, 3, 5]

    def test_overlapping_and_duplicate_tokens_are_deduplicated(self):
        assert parse_page_range("1-3,2-4,3", 5) == [1, 2, 3, 4]

    def test_single_page_range_start_equals_end(self):
        assert parse_page_range("2-2", 5) == [2]

    @pytest.mark.parametrize("spec", ["abc", "1-", "-3", "1-2-3", "1..3"])
    def test_malformed_tokens_raise(self, spec):
        with pytest.raises(PageRangeError):
            parse_page_range(spec, 5)

    def test_empty_token_between_commas_is_tolerated(self):
        """A stray double-comma shouldn't reject an otherwise-valid
        spec - forgiving of minor typos rather than punishing them."""
        assert parse_page_range("1,,2", 5) == [1, 2]

    def test_range_start_after_end_raises(self):
        with pytest.raises(PageRangeError, match="starts after it ends"):
            parse_page_range("5-2", 5)

    def test_page_zero_raises(self):
        with pytest.raises(PageRangeError, match="doesn't exist"):
            parse_page_range("0", 5)

    def test_page_beyond_max_raises(self):
        with pytest.raises(PageRangeError, match="doesn't exist"):
            parse_page_range("6", 5)

    def test_range_partially_out_of_bounds_raises(self):
        with pytest.raises(PageRangeError, match="doesn't exist"):
            parse_page_range("3-6", 5)

    def test_negative_page_raises(self):
        with pytest.raises(PageRangeError):
            parse_page_range("-1", 5)

    def test_only_commas_raises(self):
        with pytest.raises(PageRangeError, match="no pages specified"):
            parse_page_range(",,,", 5)


class TestDescribePageRange:
    def test_every_page_reads_as_all(self):
        assert describe_page_range([1, 2, 3], 3) == "All 3 pages"

    def test_single_total_page_uses_singular(self):
        assert describe_page_range([1], 1) == "All 1 page"

    def test_subset_shows_spans_and_count(self):
        assert describe_page_range([1, 2, 3, 5], 8) == "Pages 1-3, 5 (4 of 8)"

    def test_unsorted_input_is_sorted_first(self):
        assert describe_page_range([5, 1, 3, 2], 8) == "Pages 1-3, 5 (4 of 8)"

    def test_single_page_subset(self):
        assert describe_page_range([4], 8) == "Pages 4 (1 of 8)"
