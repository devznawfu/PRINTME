from pathlib import Path

import pytest

from printme.services.face_detection import (
    ImageReadError,
    count_faces,
    detect_faces,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_zero_faces_detected():
    assert count_faces(FIXTURES / "face_zero.jpg") == 0
    assert detect_faces(FIXTURES / "face_zero.jpg") == []


def test_one_face_detected():
    assert count_faces(FIXTURES / "face_one.jpg") == 1


def test_two_faces_detected():
    assert count_faces(FIXTURES / "face_two.jpg") == 2


def test_detect_faces_returns_plain_int_bounding_boxes():
    boxes = detect_faces(FIXTURES / "face_one.jpg")
    assert len(boxes) == 1
    box = boxes[0]
    assert len(box) == 4
    assert all(isinstance(v, int) for v in box)


def test_unreadable_path_raises():
    with pytest.raises(ImageReadError):
        detect_faces(FIXTURES / "does_not_exist.jpg")
