"""Review flow for flagged (needs_attention) jobs - design-reference/
admin-dashboard.html's review modal, adapted as its own page rather
than a JS overlay (same data/actions, simpler to build and test
server-rendered; not a behavior change).
"""

from pathlib import Path

from flask import Blueprint, abort, redirect, render_template, send_file, url_for

from printme.extensions import db
from printme.models.job import Job
from printme.routes.admin_auth import admin_required

bp = Blueprint("admin_review", __name__, url_prefix="/admin/jobs")


@bp.route("/<int:job_id>/review", methods=["GET"])
@admin_required
def review(job_id):
    job = db.session.get(Job, job_id)
    if job is None or not job.needs_attention:
        abort(404)
    return render_template("admin/review.html", job=job)


def _send_job_image(job_id, path_attr):
    job = db.session.get(Job, job_id)
    path = getattr(job, path_attr, None) if job else None
    if not path or not Path(path).exists():
        abort(404)
    return send_file(path)


@bp.route("/<int:job_id>/original-image", methods=["GET"])
@admin_required
def original_image(job_id):
    return _send_job_image(job_id, "upload_path")


@bp.route("/<int:job_id>/processed-image", methods=["GET"])
@admin_required
def processed_image(job_id):
    return _send_job_image(job_id, "processed_path")


@bp.route("/<int:job_id>/approve", methods=["POST"])
@admin_required
def approve(job_id):
    """Staff looked at the automatic clean-up and it's fine - clear the
    flag so it's picked up by the next Photo Sheets batch."""
    job = db.session.get(Job, job_id)
    if job is not None:
        job.clear_attention()
        db.session.commit()
    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/<int:job_id>/use-original", methods=["POST"])
@admin_required
def use_original(job_id):
    """Skip the (flawed) automatic clean-up and print the original
    upload as-is instead."""
    job = db.session.get(Job, job_id)
    if job is not None:
        job.processed_path = job.upload_path
        job.clear_attention()
        db.session.commit()
    return redirect(url_for("admin_dashboard.dashboard"))


@bp.route("/<int:job_id>/send-back", methods=["POST"])
@admin_required
def send_back(job_id):
    """Neither automatic result is good enough - hold at the counter
    for the customer to sort out in person. Nothing gets printed; the
    flag (and its reason) stays so the job is still visible and
    explained in the Needs Attention queue."""
    job = db.session.get(Job, job_id)
    if job is not None:
        job.flag_for_attention(
            f"Waiting at the counter - ask {job.customer_name.split(' ')[0]} "
            "which version to print. Nothing printed yet."
        )
        db.session.commit()
    return redirect(url_for("admin_dashboard.dashboard"))
