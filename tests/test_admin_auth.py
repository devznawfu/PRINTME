"""Tests for the actual login route logic (printme/routes/admin_auth.py).
Other test files' login() helpers set the session directly, which
bypasses do_login() entirely - these exercise the real thing."""


class TestDoLogin:
    def test_correct_username_and_password_succeeds(self, app, client):
        with app.app_context():
            username = app.config["ADMIN_USERNAME"]
            password = app.config["ADMIN_PASSWORD"]

        resp = client.post("/admin/login", data={"username": username, "password": password})

        assert resp.status_code == 302
        assert resp.headers["Location"].endswith("/admin/")

    def test_wrong_password_rejected(self, app, client):
        with app.app_context():
            username = app.config["ADMIN_USERNAME"]

        resp = client.post("/admin/login", data={"username": username, "password": "not-the-password"})

        assert resp.status_code == 400
        assert b"didn" in resp.data  # "didn't work"

    def test_wrong_username_rejected_even_with_correct_password(self, app, client):
        with app.app_context():
            password = app.config["ADMIN_PASSWORD"]

        resp = client.post("/admin/login", data={"username": "not-the-username", "password": password})

        assert resp.status_code == 400

    def test_successful_login_sets_display_name_from_submitted_username(self, app, client):
        with app.app_context():
            username = app.config["ADMIN_USERNAME"]
            password = app.config["ADMIN_PASSWORD"]

        client.post("/admin/login", data={"username": username, "password": password})

        with client.session_transaction() as sess:
            assert sess["admin_display_name"] == username
            assert sess["admin_authed"] is True

    def test_dashboard_requires_login(self, client):
        resp = client.get("/admin/")
        assert resp.status_code == 302
        assert "/admin/login" in resp.headers["Location"]
