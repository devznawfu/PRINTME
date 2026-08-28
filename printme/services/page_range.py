"""Page-range parsing for document print jobs. Pure module - no Flask/
DB/win32 imports - so it's trivially unit-testable and reusable from
both the print route and (indirectly) any future preview code, mirroring
why win32_backend.py's _match_borderless_paper_id is kept pure.
"""


class PageRangeError(ValueError):
    """A page-range string is malformed or references a page outside
    the document - never silently clamped, since this drives real
    paper/ink cost."""


def parse_page_range(spec, max_pages):
    """1-indexed pages named by `spec` (e.g. "1-3,5,7-9"), as a sorted,
    deduplicated list. A blank/None spec means every page, 1..max_pages.
    Raises PageRangeError on any malformed token or any page outside
    [1, max_pages]."""
    if not spec or not spec.strip():
        return list(range(1, max_pages + 1))

    pages = set()
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            continue
        if "-" in token:
            start_raw, _, end_raw = token.partition("-")
            start, end = start_raw.strip(), end_raw.strip()
            if not start.isdigit() or not end.isdigit():
                raise PageRangeError(f"'{token}' isn't a valid page range")
            start_n, end_n = int(start), int(end)
            if start_n > end_n:
                raise PageRangeError(f"'{token}' starts after it ends")
            pages.update(range(start_n, end_n + 1))
        else:
            if not token.isdigit():
                raise PageRangeError(f"'{token}' isn't a valid page number")
            pages.add(int(token))

    if not pages:
        raise PageRangeError("no pages specified")

    out_of_bounds = sorted(p for p in pages if p < 1 or p > max_pages)
    if out_of_bounds:
        bad = ", ".join(str(p) for p in out_of_bounds)
        raise PageRangeError(f"page {bad} doesn't exist in this {max_pages}-page document")

    return sorted(pages)


def describe_page_range(pages, max_pages):
    """A human-readable summary, e.g. "All 8 pages" or
    "Pages 1-3, 5 (5 of 8)"."""
    if list(pages) == list(range(1, max_pages + 1)):
        return f"All {max_pages} page{'s' if max_pages != 1 else ''}"

    ordered = sorted(set(pages))
    spans = []
    start = prev = ordered[0]
    for p in ordered[1:]:
        if p == prev + 1:
            prev = p
            continue
        spans.append(f"{start}-{prev}" if start != prev else str(start))
        start = prev = p
    spans.append(f"{start}-{prev}" if start != prev else str(start))

    return f"Pages {', '.join(spans)} ({len(ordered)} of {max_pages})"
