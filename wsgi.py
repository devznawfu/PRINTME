import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config import INSTANCE_DIR
from printme import create_app

app = create_app("prod")

if __name__ == "__main__":
    from flask_migrate import upgrade
    from waitress import serve

    # This is the always-on production launch path (Task Scheduler runs
    # this via pythonw.exe at log on - see scripts/install_startup_task.ps1),
    # with no visible console for anyone to read errors from - a log file
    # is the only place a failure here is ever seen.
    log_path = INSTANCE_DIR / "printme.log"
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)
    app.logger.addHandler(handler)

    # Runs `flask db upgrade` automatically on every launch instead of
    # requiring someone to remember to run it by hand - idempotent
    # (Alembic no-ops when already at head), so this is the ONLY
    # migration step that ever needs to happen again: restart the
    # service (or reboot) after copying in an update, and the schema
    # catches up on its own before anything tries to query it.
    try:
        with app.app_context():
            upgrade()
    except Exception:
        logging.getLogger(__name__).exception(
            "database migration failed at startup - refusing to serve "
            "with a possibly-stale schema"
        )
        sys.exit(1)

    try:
        # SERVE_HOST defaults to 0.0.0.0 (every interface) but should be
        # locked to the admin PC's reserved IP on the dedicated customer
        # router (e.g. 192.168.50.2) in production - otherwise anything
        # else the PC is connected to (the shop's main WiFi, a VPN/WSL
        # virtual adapter) can reach the print queue too, not just
        # customers on the intended network.
        host = os.environ.get("SERVE_HOST", "0.0.0.0")
        serve(app, host=host, port=5000)
    except Exception:
        # Under pythonw.exe there is no console at all - an uncaught
        # exception here (e.g. port 5000 already in use, maybe a
        # previous instance that didn't shut down cleanly) would
        # otherwise vanish completely instead of landing in the one
        # place anyone could find it.
        logging.getLogger(__name__).exception("server failed to start")
        sys.exit(1)
