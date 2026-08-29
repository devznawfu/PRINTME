"""Close-of-day summary (turn 5a): a read-only snapshot for the owner/
staff to check before locking up - jobs done today, paper used, and a
busiest-hour view of when customers came in. Deliberately no profit
figure and no week-over-week comparison, both explicitly out of scope
per the design doc this was built from.

Also holds Failure Analysis (turn 5b): reprint reasons ranked over the
last 30 days, since a reprint IS the concrete evidence of something
that went wrong on the original job - reusing turn 3c's reprint_of/
reprint_reason columns rather than inventing a separate failure log.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template

from printme.extensions import db
from printme.models.job import REPRINT_REASON_LABELS, Job, JobStatus
from printme.models.photo_sheet import PhotoSheet
from printme.models.pricing import rate_map
from printme.routes.admin_auth import admin_required
from printme.routes.admin_photo_sheets import _paper_key, _paper_label

bp = Blueprint("admin_day", __name__, url_prefix="/admin")

FAILURE_WINDOW_DAYS = 30


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
    revenue_collected = sum(costs)

    # "Uncollected" scoping decision: there is no "collected"/"picked up"
    # flag anywhere in this system (CLAUDE.md keeps payment physical/cash
    # and explicitly out of scope) - PRINTING is the closest existing
    # status to "money not yet closed out for today," since a job only
    # leaves PRINTING once staff mark it done at the counter.
    printing_today = Job.query.filter(
        Job.status == JobStatus.PRINTING, Job.created_at >= today_start
    ).all()
    uncollected_total = sum(j.total_cost or 0 for j in printing_today)

    # "Never collected" is deliberately NOT scoped to today - it's the
    # shop's whole backlog of jobs that finished printing but were never
    # picked up ("stay on the shelf until you clear them"), which is a
    # different question from today's still-printing count above.
    never_collected = (
        Job.query.filter(Job.status == JobStatus.PRINTING)
        .order_by(Job.created_at)
        .all()
    )

    # Paper breakdown reuses turn 3a's own grouping (finish, quality) -
    # that's the real physical reorder decision in this app's model
    # (every sheet belongs to exactly one job, which sets one finish/
    # quality for its whole order), not a per-print-size split.
    photo_sheets_today = PhotoSheet.query.filter(
        PhotoSheet.created_at >= today_start
    ).all()
    paper_counts = {}
    for sheet in photo_sheets_today:
        sheet.job = db.session.get(Job, sheet.items[0].job_id) if sheet.items else None
        key = _paper_key(sheet)
        paper_counts[key] = paper_counts.get(key, 0) + 1
    paper_breakdown = sorted(
        (
            {"label": _paper_label(key), "count": count}
            for key, count in paper_counts.items()
        ),
        key=lambda r: -r["count"],
    )

    document_sheets_today = sum(
        (j.page_count or 1) * (j.copies or 1)
        for j in done_today
        if j.service_type == "document"
    )
    if document_sheets_today:
        paper_breakdown.append({"label": "A4 documents", "count": document_sheets_today})

    sheets_today = len(photo_sheets_today) + document_sheets_today

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
        revenue_collected=revenue_collected,
        uncollected_total=uncollected_total,
        printing_count=len(printing_today),
        sheets_today=sheets_today,
        paper_breakdown=paper_breakdown,
        never_collected=never_collected,
        busiest_hours=busiest_hours,
        jobs_today_count=len(jobs_today),
    )


@bp.route("/failures", methods=["GET"])
@admin_required
def failures():
    cutoff = _today_start() - timedelta(days=FAILURE_WINDOW_DAYS - 1)
    reprints = Job.query.filter(
        Job.reprint_of.isnot(None), Job.created_at >= cutoff
    ).all()

    cost_per_sheet = rate_map(db.session).get("cost_per_sheet", 0.0)

    # A charged ("charge normally") reprint has a real customer-price
    # total_cost - use that. An uncharged ($0, shop-fault) reprint still
    # cost the shop real paper/ink, so it's estimated at cost_per_sheet
    # instead. This is a flat per-reprint estimate, not a real sheet
    # count (that would require re-running the packer for jobs that may
    # not even be packed yet) - deliberately simple, per the "scoped
    # small" plan for this feature.
    by_reason = {}
    for job in reprints:
        if not job.reprint_reason:
            continue
        entry = by_reason.setdefault(job.reprint_reason, {"count": 0, "cost": 0.0})
        entry["count"] += 1
        entry["cost"] += job.total_cost if job.total_cost else cost_per_sheet

    ranked = sorted(
        (
            {
                "reason": reason,
                "label": REPRINT_REASON_LABELS.get(reason, reason),
                "count": stats["count"],
                "cost": stats["cost"],
            }
            for reason, stats in by_reason.items()
        ),
        key=lambda r: r["count"],
        reverse=True,
    )
    total_reprints = len(reprints)
    top_reason_pct = (
        round(100 * ranked[0]["count"] / total_reprints) if ranked and total_reprints else 0
    )

    failed_count = Job.query.filter(
        Job.status == JobStatus.FAILED, Job.created_at >= cutoff
    ).count()

    return render_template(
        "admin/failures.html",
        ranked=ranked,
        total_reprints=total_reprints,
        total_cost=sum(r["cost"] for r in ranked),
        window_days=FAILURE_WINDOW_DAYS,
        cost_per_sheet=cost_per_sheet,
        top_reason_pct=top_reason_pct,
        failed_count=failed_count,
    )
