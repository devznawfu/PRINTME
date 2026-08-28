"""Editable pricing rates (CLAUDE.md defaults). Cost only - payment is
handled physically at the counter, outside this system."""

from printme.extensions import db
from printme.models.job import PAPER_FINISHES, QUALITY_LEVELS

# Every photo size's base price - the SAME regardless of finish/quality
# initially, since those are separate axes an admin differentiates
# from the pricing page, not something this codebase should guess at.
_PHOTO_BASE_RATES = {
    "1x1": 15.0,
    "2x2": 15.0,
    "Passport": 20.0,
    "Visa": 20.0,
    "Wallet": 20.0,
    "4x6": 35.0,
    "5x7": 50.0,
    "4x4": 25.0,
}

DEFAULT_RATES = {"bw_page": 5.0, "color_page": 10.0}
for _size, _base_price in _PHOTO_BASE_RATES.items():
    for _finish in PAPER_FINISHES:
        for _quality in QUALITY_LEVELS:
            DEFAULT_RATES[f"{_size}-{_finish}-{_quality}"] = _base_price
del _size, _base_price, _finish, _quality

# Not a customer-facing price - the shop's own estimated cost (paper +
# ink) per printed A4 sheet, used only by the failure-analysis page
# (turn 5b) to put a peso figure on reprints. Stored in the same table
# since PricingRate is already a generic editable key->value store and
# this needs zero new schema - kept out of DEFAULT_RATES's own naming
# though, since admin/pricing.html's customer-facing display is a
# curated allowlist (DOCUMENT_RATE_LABELS + PHOTO_SIZES_PX), not a
# blind iteration, so this key never accidentally shows up there as if
# it were a price charged to a customer.
INTERNAL_COST_KEYS = {"cost_per_sheet": 3.0}


class PricingRate(db.Model):
    __tablename__ = "pricing_rates"

    key = db.Column(db.String(32), primary_key=True)
    price = db.Column(db.Float, nullable=False)


def seed_defaults(session):
    """Insert any missing default rates. Idempotent - existing rows
    (admin-edited prices) are never overwritten."""
    existing = {
        k for (k,) in session.query(PricingRate.key).all()
    }
    for key, price in {**DEFAULT_RATES, **INTERNAL_COST_KEYS}.items():
        if key not in existing:
            session.add(PricingRate(key=key, price=price))
    session.commit()


def rate_map(session):
    """All rates as a plain dict, e.g. for the pricing engine."""
    return {r.key: r.price for r in session.query(PricingRate).all()}
