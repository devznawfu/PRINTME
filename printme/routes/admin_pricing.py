"""Editable pricing rates (CLAUDE.md: "Editable rates in admin ...
admin can edit"). Rates are seeded with defaults at app startup
(printme/__init__.py); this page lets staff override them."""

from flask import Blueprint, redirect, render_template, request, url_for

from printme.extensions import db
from printme.models.pricing import PricingRate
from printme.routes.admin_auth import admin_required
from printme.services.pricing import reprice_active_jobs

bp = Blueprint("admin_pricing", __name__, url_prefix="/admin/pricing")

RATE_LABELS = {
    "bw_page": "B&W (per page)",
    "color_page": "Color (per page)",
    "1x1": "1x1",
    "2x2": "2x2",
    "Passport": "Passport",
    "Visa": "Visa",
    "Wallet": "Wallet",
    "4x6": "4x6",
    "5x7": "5x7",
    "4x4": "4x4",
}


@bp.route("/", methods=["GET"])
@admin_required
def pricing():
    rates = PricingRate.query.order_by(PricingRate.key).all()
    return render_template("admin/pricing.html", rates=rates, rate_labels=RATE_LABELS)


@bp.route("/", methods=["POST"])
@admin_required
def update_pricing():
    for rate in PricingRate.query.all():
        raw = request.form.get(rate.key)
        try:
            rate.price = float(raw)
        except (TypeError, ValueError):
            continue
    db.session.commit()
    reprice_active_jobs(db.session)
    return redirect(url_for("admin_pricing.pricing"))
