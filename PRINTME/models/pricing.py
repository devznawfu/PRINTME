"""Editable pricing rates (CLAUDE.md defaults). Cost only - payment is
handled physically at the counter, outside this system."""

from printme.extensions import db

DEFAULT_RATES = {
    "bw_page": 5.0,
    "color_page": 10.0,
    "1x1": 15.0,
    "2x2": 15.0,
    "Passport": 20.0,
    "Visa": 20.0,
}


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
    for key, price in DEFAULT_RATES.items():
        if key not in existing:
            session.add(PricingRate(key=key, price=price))
    session.commit()


def rate_map(session):
    """All rates as a plain dict, e.g. for the pricing engine."""
    return {r.key: r.price for r in session.query(PricingRate).all()}
