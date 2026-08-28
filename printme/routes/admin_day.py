"""Close-of-day summary (turn 5a): a read-only snapshot for the owner/
staff to check before locking up - jobs done today, paper used, and a
busiest-hour view of when customers came in. Deliberately no profit
figure and no week-over-week comparison, both explicitly out of scope
per the design doc this was built from.
"""

from collections import Counter
from datetime import datetime, timezone

from flask import Blueprint, render_template

from printme.models.job import Job, JobStatus
from printme.models.photo_sheet import PhotoSheet
from printme.routes.admin_auth import admin_required

bp = Blueprint("admin_day", __name__, url_prefix="/admin")


def _today_start():
    # Same naive-UTC idiom as services/retention.py's _utc_now_naive():
    # Job.created_at is written from an aware UTC datetime but SQLite has
    # no timezone-aware column type, so it always reads back naive - the
    # cutoff must be naive too or every comparison would silently fail.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


@bp.route("/day", methods=["GET"])
@admin_required
def day_summary():
    today_start = _today_start()

    done_today = (
        Job.query.filter(Job.status == JobStatus.DONE, Job.updated_at >= today_start)
        .order_by(Job.updated_at)
        .all()
    )
    costs = [j.total_cost for j in done_today if j.total_cost is not None]
    average_cost = sum(costs) / len(costs) if costs else None

    # "Uncollected" scoping decision: there is no "collected"/"picked up"
    # flag anywhere in this system (CLAUDE.md keeps payment physical/cash
    # and explicitly out of scope) - PRINTING is the closest existing
    # status to "money not yet closed out for today," since a job only
    # leaves PRINTING once staff mark it done at the counter.
    printing_today = Job.query.filter(
        Job.status == JobStatus.PRINTING, Job.created_at >= today_start
    ).all()
    uncollected_total = sum(j.total_cost or 0 for j in printing_today)

    sheets_today = PhotoSheet.query.filter(PhotoSheet.created_at >= today_start).count()

    jobs_today = Job.query.filter(Job.created_at >= today_start).all()
    hour_counts = Counter(j.created_at.hour for j in jobs_today)
    max_hour_count = max(hour_counts.values()) if hour_counts else 0
    busiest_hours = [
        {
            "hour": hour,
            "count": hour_counts.get(hour, 0),
            "pct": round(100 * hour_counts.get(hour, 0) / max_hour_count)
            if max_hour_count
            else 0,
        }
        for hour in range(24)
        if hour_counts.get(hour, 0) > 0
    ]

    return render_template(
        "admin/day.html",
        done_count=len(done_today),
        average_cost=average_cost,
        uncollected_total=uncollected_total,
        printing_count=len(printing_today),
        sheets_today=sheets_today,
        busiest_hours=busiest_hours,
        jobs_today_count=len(jobs_today),
    )
