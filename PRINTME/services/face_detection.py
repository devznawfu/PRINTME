"""Face detection for the photo pipeline.

Uses OpenCV's Haar cascade classifier, which ships inside the
opencv-python wheel (cv2.data.haarcascades) with no network fetch -
unlike rembg's model or OpenCV's DNN face detectors, this never reaches
out to the internet, keeping the pipeline offline per CLAUDE.md.
"""

import cv2

_CASCADE_FILENAME = "haarcascade_frontalface_default.xml"
_cascade = None


class ImageReadError(Exception):
    """The image at the given path could not be read/decoded."""


def _get_cascade():
    global _cascade
    if _cascade is None:
        path = cv2.data.haarcascades + _CASCADE_FILENAME
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            raise RuntimeError(f"failed to load Haar cascade from {path}")
        _cascade = cascade
    return _cascade


def detect_faces(image_path):
    """Bounding boxes (x, y, w, h) for every face found in the image at
    image_path. An empty list means zero faces detected."""
    image = cv2.imread(str(image_path))
    if image is None:
        raise ImageReadError(f"could not read image: {image_path}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    boxes = _get_cascade().detectMultiScale(
        gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
    )
    return [tuple(int(v) for v in box) for box in boxes]


def count_faces(image_path):
    return len(detect_faces(image_path))
