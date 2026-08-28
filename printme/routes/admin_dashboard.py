"""Admin dashboard: today's code banner, Ready to Print queue
(unflagged ready-for-review jobs), Needs Attention queue (flagged ones,
each with its specific reason) - design-reference/admin-dashboard.html.
"""

from flask import Blueprint, Response, jsonify, render_template, request, session

from printme.extensions import db
from printme.models.job import Job, JobStatus
from printme.routes.admin_auth import admin_required
from printme.services.printing.printer_registry import available_printers
from printme.services.qr import generate_upload_qr_png
from printme.services.retention import free_space_bytes
from printme.services.secret_code import get_current

bp = Blueprint("admin_dashboard", __name__, url_prefix="/admin")


def file_line_for(job):
    """"N prints total" / "N copies" - shared with api.py's adjust_qty
    so a live quantity change can report back text that matches
    exactly what a full page reload would show, instead of the qty
    stepper only updating its own row's number and leaving the card's
    summary line stale."""
    if job.service_type == "photo":
        total_qty = sum(row.quantity for row in job.photo_items)
        return f"{total_qty} {'print' if total_qty == 1 else 'prints'} total"
    qty = job.copies or 1
    return f"{qty} {'copy' if qty == 1 else 'copies'}"


def _card(job):
    if job.service_type == "photo":
        rows = [
            {"row_id": row.id, "size_name": row.size_name, "quantity": row.quantity}
            for row in job.photo_items
        ]
        service_label = "Photo printing"
    else:
        rows = None
        service_label = "Document printing"

    return {
        "job": job,
        "service_label": service_label,
        "file_line": file_line_for(job),
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


@bp.route("/status", methods=["GET"])
@admin_required
def status():
    """Cheap polling endpoint for admin-auto-refresh.js: a fingerprint
    (count + latest update time) of every job currently shown on this
    dashboard. The JS polls this every few seconds and reloads the
    page only when it actually changes - so staff never have to
    manually refresh to see a new job arrive, a quantity change, or a
    job get flagged/cancelled, but nothing reloads out from under an
    admin mid-action (e.g. the crop dialog open) for no reason.

    Scoped to READY_FOR_REVIEW jobs - exactly the set the dashboard
    itself queries into ready_cards/flagged_cards - so a status change
    that moves a job out of that set (printed, cancelled) changes the
    count and is caught too, not just edits to jobs still in it.
    """
    relevant = Job.query.filter(Job.status == JobStatus.READY_FOR_REVIEW)
    count = relevant.count()
    latest = db.session.query(db.func.max(Job.updated_at)).filter(
        Job.status == JobStatus.READY_FOR_REVIEW
    ).scalar()
    return jsonify(count=count, latest=latest.isoformat() if latest else None)


@bp.route("/qr-code.png", methods=["GET"])
@admin_required
def qr_code():
    """QR code encoding the upload portal's address as actually being
    reached right now (request.host_url) - not a hardcoded address,
    since the LAN IP can change whenever the router hands out a new
    lease. Print this and post it at the counter for customers to
    scan."""
    png_bytes = generate_upload_qr_png(request.host_url)
    return Response(png_bytes, mimetype="image/png")
