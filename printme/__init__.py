import os

from flask import Flask
from sqlalchemy.exc import OperationalError

from config import CONFIG_BY_NAME
from printme.extensions import db, migrate


def create_app(config_name=None):
    app = Flask(__name__)

    config_name = config_name or os.environ.get("FLASK_ENV", "dev")
    app.config.from_object(CONFIG_BY_NAME[config_name])

    from config import INSTANCE_DIR

    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    app.config["UPLOAD_DIR"].mkdir(parents=True, exist_ok=True)
    app.config["PROCESSED_DIR"].mkdir(parents=True, exist_ok=True)

    db.init_app(app)
    migrate.init_app(app, db)

    import printme.models  # noqa: F401  (register models with db.metadata)

    from printme.routes.admin_auth import bp as admin_auth_bp
    from printme.routes.admin_dashboard import bp as admin_dashboard_bp
    from printme.routes.admin_history import bp as admin_history_bp
    from printme.routes.admin_photo_sheets import bp as admin_photo_sheets_bp
    from printme.routes.admin_pricing import bp as admin_pricing_bp
    from printme.routes.admin_review import bp as admin_review_bp
    from printme.routes.api import bp as api_bp
    from printme.routes.upload import bp as upload_bp

    app.register_blueprint(upload_bp)
    app.register_blueprint(admin_auth_bp)
    app.register_blueprint(admin_dashboard_bp)
    app.register_blueprint(admin_review_bp)
    app.register_blueprint(admin_photo_sheets_bp)
    app.register_blueprint(admin_pricing_bp)
    app.register_blueprint(admin_history_bp)
    app.register_blueprint(api_bp)

    from scheduler import init_scheduler

    init_scheduler(app)

    # Seed today's secret code and default pricing rates so both exist
    # before the dashboard renders - "ready and visible the moment the
    # admin dashboard is opened", and rates available before the first
    # job needs pricing. Skipped silently when tables don't exist yet
    # (e.g. before `flask db upgrade` has ever run on a fresh install).
    if not app.config.get("TESTING"):
        try:
            with app.app_context():
                from printme.models.pricing import seed_defaults
                from printme.services.secret_code import get_current

                seed_defaults(db.session)
                get_current(db.session)
        except OperationalError:
            app.logger.warning(
                "DB tables missing - run `flask db upgrade`; "
                "secret code and pricing rates not seeded at startup"
            )

    return app
