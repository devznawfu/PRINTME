"""Whether a service or a specific photo size can be picked on the
customer upload page right now - e.g. "we're out of glossy 4x6 paper,
hide it for today." Deliberately separate from PricingRate: this is
about whether something can be chosen at all, not what it costs.
"""

from config import PHOTO_SIZES
from printme.extensions import db

SERVICE_KEYS = ("service:photo", "service:document")


def size_key(size_name):
    return f"size:{size_name}"


class Availability(db.Model):
    __tablename__ = "availability"

    key = db.Column(db.String(32), primary_key=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)


def seed_defaults(session):
    """Insert any missing keys as enabled=True. Idempotent - existing
    rows (an admin's actual on/off choice) are never overwritten."""
    existing = {k for (k,) in session.query(Availability.key).all()}
    all_keys = list(SERVICE_KEYS) + [size_key(s) for s in PHOTO_SIZES]
    for key in all_keys:
        if key not in existing:
            session.add(Availability(key=key, enabled=True))
    session.commit()


def availability_map(session):
    """All availability flags as a plain {key: bool} dict."""
    return {a.key: a.enabled for a in session.query(Availability).all()}
