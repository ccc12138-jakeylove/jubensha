import pytest

from jubensha.storage.events import EventStore
from jubensha.storage.jobs import CompileJobs, EvalJobs


def test_compile_job_recovers_and_retries_failure(tmp_path):
    events = EventStore(tmp_path / "jobs.db")
    jobs = CompileJobs(events)
    job = jobs.create("upload_1", "key_1")
    assert jobs.claim_next()["job_id"] == job["job_id"]
    jobs = CompileJobs(events)
    assert jobs.get(job["job_id"])["status"] == "queued"
    jobs.claim_next()
    jobs.finish(job["job_id"], error="model unavailable")
    assert jobs.retry(job["job_id"])["status"] == "queued"
    jobs.claim_next()
    jobs.finish(job["job_id"], script_id="draft_1")
    assert jobs.get(job["job_id"])["script_id"] == "draft_1"
    with pytest.raises(ValueError, match="different upload"):
        jobs.create("upload_2", "key_1")


def test_eval_job_recovers_and_retries_failure(tmp_path):
    events = EventStore(tmp_path / "jobs.db")
    jobs = EvalJobs(events)
    job = jobs.create("script_1", 5, True, "eval_key")
    assert jobs.claim_next()["job_id"] == job["job_id"]
    jobs = EvalJobs(events)
    assert jobs.get(job["job_id"])["status"] == "queued"
    jobs.claim_next()
    jobs.finish(job["job_id"], error="model unavailable")
    assert jobs.retry(job["job_id"])["status"] == "queued"
    jobs.claim_next()
    jobs.finish(job["job_id"], run_id="run_1", metrics={"games": 20})
    assert jobs.get(job["job_id"])["metrics"] == {"games": 20}
