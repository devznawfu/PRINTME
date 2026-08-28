"""Editable pricing rates (CLAUDE.md: "Editable rates in admin ...
admin can edit"). Rates are seeded with defaults at app startup
(printme/__init__.py); this page lets staff override them."""

from flask import Blueprint, redirect, render_template, request, url_for

from printme.extensions import db
from printme.layout_engine.sizes import PHOTO_SIZES_PX
from printme.models.job import PAPER_FINISHES, QUALITY_LEVELS
from printme.models.pricing import INTERNAL_COST_KEYS, PricingRate
from printme.routes.admin_auth import admin_required
from printme.services.pricing import reprice_active_jobs

bp = Blueprint("admin_pricing", __name__, url_prefix="/admin/pricing")

DOCUMENT_RATE_LABELS = {
    "bw_page": "B&W (per page)",
    "color_page": "Color (per page)",
}


@bp.route("/", methods=["GET"])
@admin_required
def pricing():
    """Document rates render as a flat list (2 keys, same as always).
    Photo rates are composite ({size}-{finish}-{quality}) - grouped one
    small finish x quality table per size, rather than ~32 unlabeled
    flat rows, while update_pricing's POST handling stays completely
    generic/key-driven underneath (no restructuring needed there)."""
    rates_by_key = {r.key: r for r in PricingRate.query.all()}

    document_rates = [
        rates_by_key[key] for key in DOCUMENT_RATE_LABELS if key in rates_by_key
    ]

    photo_groups = []
    for size in PHOTO_SIZES_PX:
        cells = {}
        for finish in PAPER_FINISHES:
            for quality in QUALITY_LEVELS:
                key = f"{size}-{finish}-{quality}"
                if key in rates_by_key:
                    cells[(finish, quality)] = rates_by_key[key]
        if cells:
            photo_groups.append({"size": size, "cells": cells})

    cost_rates = [
        rates_by_key[key] for key in INTERNAL_COST_KEYS if key in rates_by_key
    ]

    return render_template(
        "admin/pricing.html",
        document_rates=document_rates,
        document_rate_labels=DOCUMENT_RATE_LABELS,
        photo_groups=photo_groups,
        finishes=PAPER_FINISHES,
        qualities=QUALITY_LEVELS,
        cost_rates=cost_rates,
        cost_rate_labels={"cost_per_sheet": "Estimated cost per A4 sheet (paper + ink)"},
    )


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
