"""Admin auth: single shared username+password (CLAUDE.md - not
per-staff accounts). Both are checked; the submitted username also
doubles as the "Signed in as X" display name on success.
"""

import secrets
from functools import wraps

from flask import Blueprint, current_app, redirect, render_template, request, session, url_for

bp = Blueprint("admin_auth", __name__, url_prefix="/admin")


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_authed"):
            return redirect(url_for("admin_auth.login"))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/login", methods=["GET"])
def login():
    if session.get("admin_authed"):
        return redirect(url_for("admin_dashboard.dashboard"))
    return render_template("admin/login.html")


@bp.route("/login", methods=["POST"])
def do_login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""

    username_ok = secrets.compare_digest(username, current_app.config["ADMIN_USERNAME"])
    password_ok = secrets.compare_digest(password, current_app.config["ADMIN_PASSWORD"])
    if username_ok and password_ok:
        session["admin_authed"] = True
        session["admin_display_name"] = username or "staff"
        return redirect(url_for("admin_dashboard.dashboard"))

    return render_template("admin/login.html", error=True, username=username), 400


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("admin_authed", None)
    session.pop("admin_display_name", None)
    return redirect(url_for("admin_auth.login"))
