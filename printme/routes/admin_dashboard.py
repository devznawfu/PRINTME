"""Admin dashboard: today's code banner, Ready to Print queue
(unflagged ready-for-review jobs), Needs Attention queue (flagged ones,
each with its specific reason) - design-reference/admin-dashboard.html.
"""

from flask import Blueprint, render_template, session

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.routes.admin_auth import admin_required
from printme.services.printing.printer_registry import available_printers
from printme.services.retention import free_space_bytes
from printme.services.secret_code import get_current

bp = Blueprint("admin_dashboard", __name__, url_prefix="/admin")


def _card(job):
    if job.service_type == "photo":
        rows = [
            {"row_id": row.id, "size_name": row.size_name, "quantity": row.quantity}
            for row in job.photo_items
        ]
        total_qty = sum(r["quantity"] for r in rows)
        thumb = rows[0]["size_name"] if len(rows) == 1 else f"{len(rows)} sizes" if rows else "Photo"
        service_label = "Photo printing"
        file_line = f"{total_qty} {'print' if total_qty == 1 else 'prints'} total"
    else:
        rows = None
        thumb = job.original_filename
        qty = job.copies or 1
        service_label = "Document printing"
        file_line = f"{qty} {'copy' if qty == 1 else 'copies'}"

    return {
        "job": job,
        "thumb": thumb,
        "service_label": service_label,
        "file_line": file_line,
        "rows": rows,
    }


@bp.route("/", methods=["GET"])
@admin_required
def dashboard():
    ready_jobs = (
        Job.query.filter(
            Job.status == JobStatus.READY_FOR_REVIEW,
            Job.needs_attention.is_(False),
        )
        .order_by(Job.created_at)
        .all()
    )
    flagged_jobs = (
        Job.query.filter(
            Job.status == JobStatus.READY_FOR_REVIEW,
            Job.needs_attention.is_(True),
        )
        .order_by(Job.created_at)
        .all()
    )
    printed_today = Job.query.filter(Job.status == JobStatus.DONE).count()
    code = get_current(db.session)

    return render_template(
        "admin/dashboard.html",
        ready_cards=[_card(j) for j in ready_jobs],
        flagged_cards=[_card(j) for j in flagged_jobs],
        todays_code=code.code,
        reset_at=code.last_reset_at,
        printed_today=printed_today,
        free_space_gb=round(free_space_bytes(".") / (1024**3), 1),
        display_name=session.get("admin_display_name", "staff"),
        printers=available_printers(),
    )
