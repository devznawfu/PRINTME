import pytest

from printme import create_app
from scheduler import init_scheduler, scheduler


@pytest.fixture
def running_scheduler():
    """init_scheduler() drives a module-level BackgroundScheduler
    singleton - start it fresh for this test and always shut it down
    afterward so no background thread leaks into other tests."""
    app = create_app("test")
    app.config["SCHEDULER_ENABLED"] = True
    init_scheduler(app)
    yield app
    if scheduler.running:
        scheduler.shutdown(wait=False)


class TestInitScheduler:
    def test_disabled_by_config_does_not_start_or_register_anything(self):
        app = create_app("test")  # TestConfig: SCHEDULER_ENABLED=False
        result = init_scheduler(app)

        assert result is None
        assert scheduler.running is False

    def test_registers_both_daily_jobs(self, running_scheduler):
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert job_ids == {"secret-code-midnight-rotation", "retention-midnight-sweep"}

    def test_jobs_are_scheduled_near_midnight_asia_manila(self, running_scheduler):
        jobs = {job.id: job for job in scheduler.get_jobs()}

        code_job = jobs["secret-code-midnight-rotation"]
        assert str(code_job.trigger.fields[5]) == "0"  # hour
        assert str(code_job.trigger.fields[6]) == "0"  # minute

        retention_job = jobs["retention-midnight-sweep"]
        assert str(retention_job.trigger.fields[5]) == "0"
        assert str(retention_job.trigger.fields[6]) == "5"

        assert str(scheduler.timezone) == "Asia/Manila"
