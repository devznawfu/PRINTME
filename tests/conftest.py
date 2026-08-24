import pytest

from printme import create_app
from printme.extensions import db


@pytest.fixture
def app(tmp_path):
    app = create_app("test")
    app.config["UPLOAD_DIR"] = tmp_path / "uploads"
    app.config["PROCESSED_DIR"] = tmp_path / "processed"
    app.config["UPLOAD_DIR"].mkdir()
    app.config["PROCESSED_DIR"].mkdir()

    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()
