"""QR code generation for the admin dashboard - lets staff print a code
customers scan to reach the upload portal, without needing to generate
one externally (which would go stale the moment the router hands out a
different LAN IP)."""

import io

import qrcode


def generate_upload_qr_png(url):
    """PNG bytes of a QR code encoding `url`."""
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
