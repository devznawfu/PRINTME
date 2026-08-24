"""APScheduler setup.

The midnight rotation job is a convenience, not a dependency: the secret
code service rotates lazily on access, so a code is never stale even if
the app was not running when midnight passed. This job just makes the
rotation happen promptly on machines that are up around the clock.

The retention sweep (CLAUDE.md: uploaded source files auto-delete after
2 days) has no such lazy fallback - a missed run just means stale files
linger an extra day, cleaned up by the next run or the admin's manual
"Delete jobs older than 2 days" button.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from printme.services.retention import DEFAULT_RETENTION_DAYS

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Manila")


def _rotate_secret_code(app):
    with app.app_context():
        from printme.extensions import db
        from printme.services.secret_code import get_current

        get_current(db.session)
        logger.info("Secret code rotation check complete")


def _sweep_old_uploads(app):
    with app.app_context():
        from printme.extensions import db
        from printme.services.retention import sweep_old_uploads

        deleted = sweep_old_uploads(db.session, days=DEFAULT_RETENTION_DAYS)
        logger.info("Retention sweep deleted %d old upload file(s)", deleted)


def init_scheduler(app):
    if not app.config.get("SCHEDULER_ENABLED"):
        return None

    scheduler.add_job(
        _rotate_secret_code,
        trigger="cron",
        hour=0,
        minute=0,
        args=[app],
        id="secret-code-midnight-rotation",
        replace_existing=True,
    )
    scheduler.add_job(
        _sweep_old_uploads,
        trigger="cron",
        hour=0,
        minute=5,
        args=[app],
        id="retention-midnight-sweep",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
