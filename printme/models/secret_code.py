"""Storage for the daily secret code (abuse prevention, CLAUDE.md).

Single-row table - app logic keeps it at id=1 via get_or_create.
"""

from datetime import date, datetime, timezone

from printme.extensions import db


class SecretCode(db.Model):
    __tablename__ = "secret_code"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(4), nullable=False)

    # The day this code was created - drives the lazy daily-rollover check
    # in the service layer.
    generated_on = db.Column(db.Date, nullable=False)

    # Last MANUAL reset ("Reset Code" button). Daily rotation deliberately
    # does not touch this - staff use it to confirm a manual reset took
    # effect. Null until someone resets by hand.
    last_reset_at = db.Column(db.DateTime)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today():
    return date.today()
