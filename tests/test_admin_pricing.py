from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, PricingRate, seed_defaults
from printme.models.pricing import rate_map


def login(client):
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
        sess["admin_display_name"] = "staff"


class TestPricingPage:
    def test_get_renders_current_rates(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
        login(client)

        resp = client.get("/admin/pricing/")

        assert resp.status_code == 200
        assert b"15.00" in resp.data  # default 1x1/2x2 rate
        assert b"35.00" in resp.data  # default 4x6 rate
        assert b"4x6" in resp.data

    def test_requires_admin_login(self, client):
        resp = client.get("/admin/pricing/")
        assert resp.status_code == 302

    def test_every_composite_rate_is_rendered_grouped_by_size(self, app, client):
        with app.app_context():
            seed_defaults(db.session)
            all_keys = {r.key for r in PricingRate.query.all()}
        login(client)

        resp = client.get("/admin/pricing/")
        body = resp.get_data(as_text=True)

        photo_keys = [k for k in all_keys if k not in ("bw_page", "color_page")]
        assert len(photo_keys) == 32  # 8 sizes x 2 finishes x 2 qualities
        for key in photo_keys:
            assert f'id="rate-{key}"' in body
        assert "Glossy, standard" in body
        assert "Bond, high" in body


class TestUpdatePricing:
    def test_post_updates_rate_and_reprices_active_jobs(self, app, client):
        with app.app_context():
            seed_defaults(db.session)

            job = Job(
                ticket_number="P-001",
                customer_name="Maria",
                service_type="photo",
                original_filename="photo.jpg",
                upload_path="/uploads/photo.jpg",
                status=JobStatus.READY_FOR_REVIEW,
            )
            job.photo_items.append(PhotoItemRow(size_name="1x1", quantity=2))
            db.session.add(job)
            db.session.commit()
            job_id = job.id

        login(client)

        with app.app_context():
            form_data = {r.key: r.price for r in PricingRate.query.all()}
        form_data["1x1-bond-standard"] = "50.00"

        resp = client.post("/admin/pricing/", data=form_data)
        assert resp.status_code == 302

        with app.app_context():
            rates = rate_map(db.session)
            assert rates["1x1-bond-standard"] == 50.0

            fetched = db.session.get(Job, job_id)
            assert fetched.total_cost == 50.0 * 2
