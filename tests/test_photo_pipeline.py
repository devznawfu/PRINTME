from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from printme.extensions import db
from printme.models import Job, JobStatus, PhotoItemRow, seed_defaults
from printme.models.pricing import rate_map
from printme.services.photo_pipeline import (
    CANONICAL_SIZE_PX,
    MIN_MANUAL_CROP_SIDE_PX,
    compute_manual_crop_box,
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


class TestComputeManualCropBox:
    def test_basic_conversion_is_centered_and_square(self):
        box = compute_manual_crop_box((400, 400), (0.25, 0.25, 0.5, 0.5))
        assert box == (100, 100, 300, 300)

    def test_overflowing_box_is_clamped_within_image_bounds(self):
        left, top, right, bottom = compute_manual_crop_box(
            (400, 400), (0.8, 0.1, 0.6, 0.6)
        )
        assert right - left == bottom - top
        assert 0 <= left < right <= 400
        assert 0 <= top < bottom <= 400

    def test_below_minimum_side_returns_none(self):
        assert (
            compute_manual_crop_box((1000, 1000), (0.4, 0.4, 0.1, 0.1)) is None
        )

    def test_at_exactly_the_minimum_side_is_accepted(self):
        side_fraction = MIN_MANUAL_CROP_SIDE_PX / 1000
        box = compute_manual_crop_box(
            (1000, 1000), (0.4, 0.4, side_fraction, side_fraction)
        )
        assert box is not None
        left, top, right, bottom = box
        assert right - left == bottom - top == MIN_MANUAL_CROP_SIDE_PX

    def test_never_exceeds_image_bounds_for_a_borderline_huge_box(self):
        left, top, right, bottom = compute_manual_crop_box(
            (1000, 800), (0.4, 0.4, 0.9, 0.9)
        )
        assert right - left == bottom - top
        assert 0 <= left < right <= 1000
        assert 0 <= top < bottom <= 800


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


class TestProcessPhotoJobManualCrop:
    def test_valid_manual_crop_is_used_and_marks_processed_source(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(upload_path=str(FIXTURES / "face_one.jpg"))
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(job)
            db.session.commit()

            result = process_photo_job(
                db.session,
                job,
                FIXTURES / "face_one.jpg",
                tmp_path,
                manual_crop_fractions=(0.1, 0.1, 0.5, 0.5),
            )

            assert Path(result.processed_path).exists()
            fetched = db.session.get(Job, job.id)
            assert fetched.processed_source == "manual"

    def test_degenerate_manual_crop_falls_back_to_automatic(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(upload_path=str(FIXTURES / "face_one.jpg"))
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(job)
            db.session.commit()

            # face_one.jpg is 512x512; a 0.05 fraction side is ~26px,
            # well under MIN_MANUAL_CROP_SIDE_PX - degenerate on purpose.
            result = process_photo_job(
                db.session,
                job,
                FIXTURES / "face_one.jpg",
                tmp_path,
                manual_crop_fractions=(0.4, 0.4, 0.05, 0.05),
            )

            assert result.face_count == 1
            assert result.needs_attention is False
            fetched = db.session.get(Job, job.id)
            assert fetched.processed_source == "auto"

    def test_no_manual_crop_still_marks_processed_source_auto(self, app, tmp_path):
        with app.app_context():
            seed_defaults(db.session)
            job = make_photo_job(upload_path=str(FIXTURES / "face_one.jpg"))
            job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(job)
            db.session.commit()

            process_photo_job(db.session, job, FIXTURES / "face_one.jpg", tmp_path)

            fetched = db.session.get(Job, job.id)
            assert fetched.processed_source == "auto"

    def test_face_count_flagging_still_fires_with_a_manual_crop_present(
        self, app, tmp_path
    ):
        """needs_attention's 0/2+-face check is about the source photo's
        content, not which crop path was used (decision #4 of the
        manual-crop plan) - proven here for real, not just documented."""
        with app.app_context():
            job = make_photo_job(upload_path=str(FIXTURES / "face_two.jpg"))
            db.session.add(job)
            db.session.commit()

            result = process_photo_job(
                db.session,
                job,
                FIXTURES / "face_two.jpg",
                tmp_path,
                manual_crop_fractions=(0.0, 0.0, 1.0, 1.0),
            )

            assert result.face_count == 2
            assert result.needs_attention is True
            assert "which person" in result.attention_reason
            fetched = db.session.get(Job, job.id)
            assert fetched.processed_source == "manual"

    def test_manual_crop_applies_exif_orientation_but_automatic_path_does_not(
        self, app, tmp_path, monkeypatch
    ):
        """A real, pre-existing gap in the automatic pipeline: browsers
        auto-rotate a preview per EXIF orientation, but cv2/PIL reads
        raw pixels. The fixture is 300x400 as stored on disk (raw
        camera-sensor orientation) with an EXIF tag saying "rotate 90
        CCW to display correctly" - the human-intended image is a
        400x300 photo split cleanly red-left/blue-right.

        Manual crop must apply ImageOps.exif_transpose() first, so its
        output should show red on the left and blue on the right (the
        intended orientation). The automatic path does NOT correct for
        EXIF (untouched, out of scope per the plan) - its output is
        pinned here to keep showing the raw, uncorrected split instead
        (red on top, blue on bottom), so a future accidental fix or
        regression to the automatic path is caught either way.

        remove_background is stubbed out for this test only: the real
        rembg model finds no "subject" in a flat two-color image (no
        face, no person) and wipes the whole thing to solid white,
        which would erase exactly the color signal this test needs -
        that's a real, separately-verified rembg behavior, not
        something this orientation test is meant to exercise."""
        import printme.services.photo_pipeline as pipeline_module

        def fake_remove_background(image, out_path):
            image.save(out_path)
            return np.full((image.height, image.width), 255, dtype=np.uint8)

        monkeypatch.setattr(pipeline_module, "remove_background", fake_remove_background)

        fixture = FIXTURES / "left_right_exif_rotated.jpg"
        with app.app_context():
            seed_defaults(db.session)

            manual_job = make_photo_job(upload_path=str(fixture))
            manual_job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(manual_job)
            db.session.commit()
            manual_result = process_photo_job(
                db.session,
                manual_job,
                fixture,
                tmp_path,
                manual_crop_fractions=(0.0, 0.0, 1.0, 1.0),
            )

            with Image.open(manual_result.processed_path) as img:
                left = img.getpixel((10, img.height // 2))
                right = img.getpixel((img.width - 10, img.height // 2))
            assert left[0] > left[2], "expected red to dominate on the left"
            assert right[2] > right[0], "expected blue to dominate on the right"

            auto_job = make_photo_job(
                ticket_number="P-002", upload_path=str(fixture)
            )
            auto_job.photo_items.append(PhotoItemRow(size_name="2x2", quantity=1))
            db.session.add(auto_job)
            db.session.commit()
            auto_result = process_photo_job(db.session, auto_job, fixture, tmp_path)

            with Image.open(auto_result.processed_path) as img:
                top = img.getpixel((img.width // 2, 10))
                bottom = img.getpixel((img.width // 2, img.height - 10))
            assert top[0] > top[2], "expected the pre-existing gap: raw (uncorrected) red on top"
            assert bottom[2] > bottom[0], "expected the pre-existing gap: raw (uncorrected) blue on bottom"


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
