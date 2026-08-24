import pytest

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults
from printme.models.pricing import rate_map
from printme.services.pricing import compute_cost, price_job, reprice_active_jobs


def make_photo_job(**rows_and_qty):
    job = Job(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path="/uploads/photo.jpg",
    )
    for size_name, qty in rows_and_qty.items():
        job.photo_items.append(PhotoItemRow(size_name=size_name, quantity=qty))
    return job


def make_document_job(**overrides):
    defaults = dict(
        ticket_number="P-002",
        customer_name="Ben",
        service_type="document",
        original_filename="doc.pdf",
        upload_path="/uploads/doc.pdf",
        color_mode="bw",
        page_count=3,
        copies=2,
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestComputeCost:
    def test_photo_job_sums_across_sizes_and_quantities(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            job = make_photo_job(**{"1x1": 2, "Passport": 3})

            cost = compute_cost(job, rates)

            assert cost == rates["1x1"] * 2 + rates["Passport"] * 3

    def test_document_job_uses_bw_or_color_rate_times_pages_times_copies(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)

            bw = make_document_job(color_mode="bw", page_count=3, copies=2)
            assert compute_cost(bw, rates) == rates["bw_page"] * 3 * 2

            color = make_document_job(color_mode="color", page_count=3, copies=2)
            assert compute_cost(color, rates) == rates["color_page"] * 3 * 2

    def test_document_job_defaults_copies_to_one_if_falsy(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            job = make_document_job(copies=None, page_count=5)
            assert compute_cost(job, rates) == rates["bw_page"] * 5

    def test_document_job_without_page_count_raises(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            job = make_document_job(page_count=None)
            with pytest.raises(ValueError, match="page_count"):
                compute_cost(job, rates)

    def test_unknown_service_type_raises(self, app):
        with app.app_context():
            seed_defaults(db.session)
            rates = rate_map(db.session)
            job = make_document_job(service_type="fax")
            with pytest.raises(ValueError, match="service_type"):
                compute_cost(job, rates)


class TestPriceJob:
    def test_price_job_persists_total_cost(self, app):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(**{"2x2": 4})
            db.session.add(job)
            db.session.commit()

            total = price_job(db.session, job)

            rates = rate_map(db.session)
            assert total == rates["2x2"] * 4
            fetched = db.session.get(Job, job.id)
            assert fetched.total_cost == total

    def test_price_job_uses_admin_edited_rates(self, app):
        with app.app_context():
            seed_defaults(db.session)
            from printme.models import PricingRate

            rate = PricingRate.query.filter_by(key="Visa").one()
            rate.price = 999.0
            db.session.commit()

            job = make_photo_job(**{"Visa": 1})
            db.session.add(job)
            db.session.commit()

            assert price_job(db.session, job) == 999.0


class TestRepriceActiveJobs:
    def test_reprices_all_active_jobs_and_skips_unpriceable_ones(self, app):
        with app.app_context():
            seed_defaults(db.session)

            priceable = make_photo_job(**{"1x1": 1})
            unpriceable_doc = make_document_job(
                ticket_number="P-003", page_count=None
            )
            done_job = make_document_job(
                ticket_number="P-004", page_count=1, status=JobStatus.DONE
            )
            db.session.add_all([priceable, unpriceable_doc, done_job])
            db.session.commit()
            done_job_id = done_job.id

            repriced = reprice_active_jobs(db.session)

            repriced_ids = {job.id for job in repriced}
            assert priceable.id in repriced_ids
            assert unpriceable_doc.id not in repriced_ids
            assert done_job_id not in repriced_ids  # not active, untouched

            rates = rate_map(db.session)
            assert priceable.total_cost == rates["1x1"]
            assert unpriceable_doc.total_cost is None
