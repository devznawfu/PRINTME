from pathlib import Path

import pytest
from PIL import Image

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults
from printme.models.pricing import rate_map
from printme.services.photo_pipeline import (
    CANONICAL_SIZE_PX,
    compute_square_crop_box,
    process_photo_job,
)

FIXTURES = Path(__file__).parent / "fixtures"


def make_photo_job(**overrides):
    defaults = dict(
        ticket_number="P-001",
        customer_name="Maria",
        service_type="photo",
        original_filename="photo.jpg",
        upload_path=str(FIXTURES / "face_one.jpg"),
    )
    defaults.update(overrides)
    return Job(**defaults)


class TestComputeSquareCropBox:
    def test_no_face_centers_on_whole_image_and_is_square(self):
        left, top, right, bottom = compute_square_crop_box((400, 200))
        assert right - left == bottom - top == 200  # side = min(w, h)
        # centered horizontally: 100px margin each side of the 200-wide crop
        assert left == 100 and right == 300
        assert top == 0 and bottom == 200

    def test_face_box_centers_crop_on_the_face(self):
        # 40px-tall face at (80, 80): side = 40 / 0.6 = ~66.67
        box = compute_square_crop_box((500, 500), face_box=(80, 80, 40, 40))
        left, top, right, bottom = box
        assert right - left == bottom - top
        cx, cy = (left + right) / 2, (top + bottom) / 2
        assert abs(cx - 100) <= 1 and abs(cy - 100) <= 1  # face center is (100, 100)

    def test_face_near_edge_is_clamped_within_image_bounds(self):
        left, top, right, bottom = compute_square_crop_box(
            (300, 300), face_box=(0, 0, 60, 60)
        )
        assert left >= 0 and top >= 0
        assert right <= 300 and bottom <= 300
        assert right - left == bottom - top

    def test_crop_never_exceeds_image_bounds_for_a_huge_face_box(self):
        # A face box whose implied side would be larger than the image.
        left, top, right, bottom = compute_square_crop_box(
            (200, 200), face_box=(50, 50, 190, 190)
        )
        assert 0 <= left < right <= 200
        assert 0 <= top < bottom <= 200


class TestProcessPhotoJobHappyPath:
    def test_one_face_produces_clean_ready_for_review_job(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(upload_path=str(FIXTURES / "face_one.jpg"))
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=2))
            db.session.add(job)
            db.session.commit()

            result = process_photo_job(db.session, job, FIXTURES / "face_one.jpg", tmp_path)

            assert result.face_count == 1
            assert result.needs_attention is False
            assert result.attention_reason is None
            assert Path(result.processed_path).exists()

            with Image.open(result.processed_path) as img:
                assert img.size == (CANONICAL_SIZE_PX, CANONICAL_SIZE_PX)

            fetched = db.session.get(Job, job.id)
            assert fetched.status == JobStatus.READY_FOR_REVIEW
            assert fetched.needs_attention is False
            assert fetched.processed_path == result.processed_path
            assert fetched.total_cost == rate_map(db.session)["2x2-bond-standard"] * 2


class TestProcessPhotoJobFlagging:
    def test_zero_faces_flags_with_specific_reason(self, app, tmp_path):
        with app.app_context():
            job = make_photo_job(upload_path=str(FIXTURES / "face_zero.jpg"))
            db.session.add(job)
            db.session.commit()

            result = process_photo_job(
                db.session, job, FIXTURES / "face_zero.jpg", tmp_path
            )

            assert result.face_count == 0
            assert result.needs_attention is True
            assert "No face" in result.attention_reason

            fetched = db.session.get(Job, job.id)
            assert fetched.needs_attention is True
            assert fetched.status == JobStatus.READY_FOR_REVIEW  # still reviewable

    def test_two_faces_flags_with_specific_reason(self, app, tmp_path):
        with app.app_context():
            job = make_photo_job(upload_path=str(FIXTURES / "face_two.jpg"))
            db.session.add(job)
            db.session.commit()

            result = process_photo_job(
                db.session, job, FIXTURES / "face_two.jpg", tmp_path
            )

            assert result.face_count == 2
            assert result.needs_attention is True
            assert "2 faces" in result.attention_reason
            assert "which person" in result.attention_reason


class TestProcessPhotoJobFailure:
    def test_unreadable_image_marks_job_failed_and_reraises(self, app, tmp_path):
        with app.app_context():
            job = make_photo_job(upload_path=str(tmp_path / "missing.jpg"))
            db.session.add(job)
            db.session.commit()

            with pytest.raises(Exception):
                process_photo_job(db.session, job, tmp_path / "missing.jpg", tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.status == JobStatus.FAILED
            assert fetched.needs_attention is True
            assert "Photo processing failed" in fetched.attention_reason
