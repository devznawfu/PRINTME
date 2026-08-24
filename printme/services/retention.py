"""File retention (CLAUDE.md): uploaded source files auto-delete after
2 days; processed photos are kept until manual admin cleanup. The admin
dashboard shows free storage space and a manual "delete jobs older
than 2 days" button - same sweep as the scheduled task, just triggered
by hand instead of by the scheduler.
"""

import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from printme.models.job import Job

DEFAULT_RETENTION_DAYS = 2


def _utc_now_naive():
    # Job.created_at is written from an aware UTC datetime but SQLite
    # has no timezone-aware column type, so it always reads back naive.
    # Compare against a naive cutoff to match.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def sweep_old_uploads(session, days=DEFAULT_RETENTION_DAYS):
    """Delete the on-disk SOURCE file (not the DB row, not the processed
    photo) for every job whose upload is older than `days` days.
    Job.upload_path is NOT NULL, so it's left as-is afterward - a
    historical record of where the file was, not a live path; callers
    must check the path still exists before trying to use it. Returns
    the number of files actually deleted (already-cleaned-up jobs, or
    ones whose file went missing some other way, aren't counted)."""
    cutoff = _utc_now_naive() - timedelta(days=days)
    stale_jobs = session.query(Job).filter(Job.created_at <= cutoff).all()

    deleted = 0
    for job in stale_jobs:
        path = Path(job.upload_path)
        if path.exists():
            path.unlink()
            deleted += 1

    return deleted


def free_space_bytes(path):
    """Free disk space at `path`, for the admin dashboard's storage
    display."""
    return shutil.disk_usage(path).free
