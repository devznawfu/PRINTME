"""Daily secret code logic: lazy daily rotation, manual reset, validation.

CLAUDE.md rules implemented here:
- Checked once, at submission time - no session gate (a customer already
  mid-upload when the code rotates is not blocked).
- Auto-rotates daily. Rotation is LAZY: any access first checks whether
  the stored code is from today and rotates if stale, so the code is
  correct even if the app was not running at midnight. The scheduler's
  midnight job is just a prompt; this module is the source of truth.
"""

import secrets
from datetime import datetime, timedelta

from printme.extensions import db
from printme.models.secret_code import SecretCode, today, utc_now

# Brute-force lockout (CLAUDE.md flag: a 4-digit code is only 10,000
# combinations). Tracked in the customer's own Flask session - "same
# session" per the ask - not a server-side store, so it resets if they
# clear cookies but that's an acceptable tradeoff for a walk-in kiosk.
MAX_CODE_ATTEMPTS = 5
LOCKOUT_WINDOW = timedelta(minutes=10)


def _random_code(previous):
    """A 4-digit code, never equal to `previous` so a reset always
    visibly changes the code."""
    while True:
        code = f"{secrets.randbelow(10000):04d}"
        if code != previous:
            return code


def get_current(session):
    """Today's SecretCode row, rotating first if the stored one is stale."""
    row = session.get(SecretCode, 1)
    now_date = today()

    if row is None:
        row = SecretCode(
            id=1, code=_random_code(None), generated_on=now_date
        )
        session.add(row)
        session.commit()
    elif row.generated_on != now_date:
        # Daily rotation - new code, but NOT a manual reset: leave
        # last_reset_at alone.
        row.code = _random_code(row.code)
        row.generated_on = now_date
        session.commit()

    return row


def reset_now(session):
    """Manual "Reset Code" button: force a new code immediately and stamp
    last_reset_at so staff can confirm the reset took effect."""
    current = get_current(session)
    current.code = _random_code(current.code)
    current.generated_on = today()
    current.last_reset_at = utc_now()
    session.commit()
    return current


def is_locked_out(flask_session):
    """True if this browser session has failed the code check
    MAX_CODE_ATTEMPTS times within LOCKOUT_WINDOW of its first failure.
    Clears the counter (and returns False) once the window has passed,
    so a customer isn't locked out forever."""
    count = flask_session.get("code_fail_count", 0)
    first_at = flask_session.get("code_fail_first_at")
    if count < MAX_CODE_ATTEMPTS or first_at is None:
        return False
    if utc_now() - datetime.fromisoformat(first_at) >= LOCKOUT_WINDOW:
        flask_session.pop("code_fail_count", None)
        flask_session.pop("code_fail_first_at", None)
        return False
    return True


def record_failed_attempt(flask_session):
    if "code_fail_first_at" not in flask_session:
        flask_session["code_fail_first_at"] = utc_now().isoformat()
    flask_session["code_fail_count"] = flask_session.get("code_fail_count", 0) + 1


def clear_code_attempts(flask_session):
    flask_session.pop("code_fail_count", None)
    flask_session.pop("code_fail_first_at", None)


def validate(submitted, session):
    """Constant-time check of a customer-submitted code against today's.
    Called once by the upload route at the moment of submission."""
    if submitted is None:
        return False
    current = get_current(session)
    return secrets.compare_digest(
        str(submitted).strip(), str(current.code)
    )
