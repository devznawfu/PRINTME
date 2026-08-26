"""Tests for the daily secret code model + service."""

from datetime import timedelta

from printme.extensions import db
from printme.models.secret_code import SecretCode
from printme.models import SecretCode as ExportedSecretCode
from printme.services import secret_code


def current_row():
    return db.session.get(SecretCode, 1)


class TestGetCurrent:
    def test_first_access_creates_todays_code(self, app):
        with app.app_context():
            row = secret_code.get_current(db.session)

            assert row.id == 1
            assert row.generated_on == secret_code.today()
            assert len(row.code) == 4 and row.code.isdigit()

    def test_same_day_access_is_stable(self, app):
        with app.app_context():
            first = secret_code.get_current(db.session)
            second = secret_code.get_current(db.session)
            assert first.code == second.code

    def test_stale_code_rotates_lazily(self, app):
        with app.app_context():
            old = secret_code.get_current(db.session)
            old_code = old.code
            old.generated_on = secret_code.today() - timedelta(days=3)
            db.session.commit()

            fresh = secret_code.get_current(db.session)
            assert fresh.code != old_code
            assert fresh.generated_on == secret_code.today()

    def test_daily_rotation_does_not_touch_last_reset_at(self, app):
        with app.app_context():
            row = secret_code.reset_now(db.session)
            stamp = row.last_reset_at  # whatever reset_now wrote
            pre_rotation_code = row.code

            row.generated_on = secret_code.today() - timedelta(days=1)
            db.session.commit()

            rotated = secret_code.get_current(db.session)
            assert rotated.code != pre_rotation_code
            assert rotated.last_reset_at == stamp


class TestResetNow:
    def test_reset_changes_code_and_stamps_time(self, app):
        with app.app_context():
            before = secret_code.get_current(db.session).code

            after = secret_code.reset_now(db.session)

            assert after.code != before
            assert after.last_reset_at is not None
            assert after.generated_on == secret_code.today()

    def test_reset_works_same_day(self, app):
        with app.app_context():
            first_code = secret_code.reset_now(db.session).code
            second_code = secret_code.reset_now(db.session).code
            assert first_code != second_code


class TestRandomness:
    def test_new_code_never_equals_previous(self, app, monkeypatch):
        """Force the generator's first pick to collide with `previous` to
        prove the retry loop rejects it."""
        with app.app_context():
            calls = {"n": 0}

            def colliding_randbelow(n):
                calls["n"] += 1
                return 1234 if calls["n"] == 1 else 5678

            monkeypatch.setattr(
                secret_code.secrets, "randbelow", colliding_randbelow
            )
            code = secret_code._random_code("1234")
            assert code == "5678"
            assert calls["n"] == 2

    def test_codes_are_well_formed_across_resets(self, app):
        with app.app_context():
            seen = set()
            for _ in range(5):
                code = secret_code.reset_now(db.session).code
                seen.add(code)
                assert len(code) == 4 and code.isdigit()
            # 5 forced resets from a 10000-code space should not all be equal
            assert len(seen) > 1


class TestValidate:
    def test_accepts_current_code(self, app):
        with app.app_context():
            code = secret_code.get_current(db.session).code
            assert secret_code.validate(code, db.session) is True

    def test_rejects_wrong_code(self, app):
        with app.app_context():
            current = secret_code.get_current(db.session).code
            wrong = "0000" if current != "0000" else "1111"
            assert secret_code.validate(wrong, db.session) is False

    def test_rejects_none_and_whitespace_noise(self, app):
        with app.app_context():
            assert secret_code.validate(None, db.session) is False
            current = secret_code.get_current(db.session).code
            # padded input still matches - staff read digits aloud
            assert (
                secret_code.validate(f"  {current} ", db.session) is True
            )

    def test_old_code_fails_after_rotation(self, app):
        with app.app_context():
            old = secret_code.get_current(db.session).code
            db.session.get(SecretCode, 1).generated_on -= timedelta(days=1)
            db.session.commit()
            secret_code.get_current(db.session)  # triggers rotation

            assert secret_code.validate(old, db.session) is False


class TestLockout:
    def test_not_locked_out_before_max_attempts(self):
        sess = {}
        for _ in range(secret_code.MAX_CODE_ATTEMPTS - 1):
            secret_code.record_failed_attempt(sess)
        assert secret_code.is_locked_out(sess) is False

    def test_locked_out_at_max_attempts_within_window(self):
        sess = {}
        for _ in range(secret_code.MAX_CODE_ATTEMPTS):
            secret_code.record_failed_attempt(sess)
        assert secret_code.is_locked_out(sess) is True

    def test_first_attempt_stamps_first_at_only_once(self):
        sess = {}
        secret_code.record_failed_attempt(sess)
        first = sess["code_fail_first_at"]
        secret_code.record_failed_attempt(sess)
        assert sess["code_fail_first_at"] == first
        assert sess["code_fail_count"] == 2

    def test_expired_window_unlocks_and_clears_counter(self):
        sess = {
            "code_fail_count": secret_code.MAX_CODE_ATTEMPTS,
            "code_fail_first_at": (
                secret_code.utc_now() - secret_code.LOCKOUT_WINDOW - timedelta(seconds=1)
            ).isoformat(),
        }
        assert secret_code.is_locked_out(sess) is False
        assert "code_fail_count" not in sess
        assert "code_fail_first_at" not in sess

    def test_clear_code_attempts_resets_state(self):
        sess = {}
        for _ in range(secret_code.MAX_CODE_ATTEMPTS):
            secret_code.record_failed_attempt(sess)
        secret_code.clear_code_attempts(sess)
        assert secret_code.is_locked_out(sess) is False
        assert "code_fail_count" not in sess


def test_model_is_exported_from_models_package():
    assert ExportedSecretCode is SecretCode
