from pathlib import Path

import numpy as np
from PIL import Image

from printme.services.background_removal import detect_artifacts, remove_background

FIXTURES = Path(__file__).parent / "fixtures"


def solid_mask(size=200, margin=40):
    """A single clean opaque blob on a transparent field - no holes,
    no fragments."""
    mask = np.zeros((size, size), dtype="uint8")
    mask[margin : size - margin, margin : size - margin] = 255
    return mask


class TestDetectArtifactsCleanMask:
    def test_clean_solid_blob_has_no_artifacts(self):
        assert detect_artifacts(solid_mask()) == []

    def test_tiny_noise_speckles_are_ignored(self):
        mask = solid_mask()
        # A handful of isolated single pixels - normal compression/
        # segmentation noise, not a real second blob.
        mask[5, 5] = 255
        mask[6, 90] = 255
        assert detect_artifacts(mask) == []


class TestDetectArtifactsFragments:
    def test_significant_second_blob_is_flagged(self):
        # Main blob 80x80=6400, second blob 40x40=1600 (25% of main,
        # well over the 8% threshold), with a clear 20px gap between
        # them so they're disconnected even under 8-connectivity.
        mask = np.zeros((200, 200), dtype="uint8")
        mask[20:100, 20:100] = 255
        mask[120:160, 120:160] = 255
        reasons = detect_artifacts(mask)
        assert any("fragment" in r.lower() for r in reasons)

    def test_small_secondary_blob_under_threshold_not_flagged(self):
        mask = solid_mask()
        # Main blob area is 120x120=14400; this blob is well under 8%.
        mask[0:10, 0:10] = 255
        assert detect_artifacts(mask) == []


class TestDetectArtifactsHoles:
    def test_hole_in_main_blob_is_flagged(self):
        mask = solid_mask()
        # A sizeable hole punched in the middle of the main blob.
        mask[90:110, 90:110] = 0
        reasons = detect_artifacts(mask)
        assert any("cut into" in r.lower() for r in reasons)

    def test_tiny_hole_under_threshold_not_flagged(self):
        mask = solid_mask()
        mask[99:101, 99:101] = 0  # 2x2 pinhole, negligible vs 120x120 blob
        assert detect_artifacts(mask) == []


class TestDetectArtifactsEmptyMask:
    def test_no_foreground_at_all_is_flagged(self):
        empty = np.zeros((200, 200), dtype="uint8")
        reasons = detect_artifacts(empty)
        assert len(reasons) == 1
        assert "no clear subject" in reasons[0].lower()


class TestRemoveBackgroundIntegration:
    def test_produces_a_white_background_image_and_a_real_mask(self, tmp_path):
        out_path = tmp_path / "cutout.png"

        alpha = remove_background(FIXTURES / "face_one.jpg", out_path)

        assert out_path.exists()
        # A real segmentation, not "everything opaque" (which would mean
        # we accidentally measured a flattened/composited alpha channel).
        assert alpha.min() < 50
        assert alpha.max() > 200

        with Image.open(out_path) as result:
            assert result.mode == "RGB"
            corner_pixel = result.getpixel((2, 2))
            assert corner_pixel == (255, 255, 255)  # corner is background

    def test_detect_artifacts_runs_clean_against_a_real_portrait(self, tmp_path):
        alpha = remove_background(FIXTURES / "face_one.jpg", tmp_path / "cutout.png")
        assert detect_artifacts(alpha) == []
