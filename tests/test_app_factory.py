def test_app_boots_in_test_config(app):
    assert app.testing is True
    assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"


def test_upload_and_processed_dirs_exist(app):
    assert app.config["UPLOAD_DIR"].is_dir()
    assert app.config["PROCESSED_DIR"].is_dir()
