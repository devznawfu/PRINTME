"""SQLite ignores FOREIGN KEY constraints unless PRAGMA foreign_keys=ON
is set per connection (printme/extensions.py). This is a cross-cutting
DB config concern, not specific to any one model, so it gets its own
test file rather than living inside one model's test module."""

import pytest
from sqlalchemy.exc import IntegrityError

from printme.extensions import db
from printme.models import PhotoItemRow


def test_foreign_key_violations_are_rejected(app):
    with app.app_context():
        # No Job with id=999999 exists.
        db.session.add(PhotoItemRow(job_id=999999, size_name="1x1", quantity=1))
        with pytest.raises(IntegrityError):
            db.session.commit()
