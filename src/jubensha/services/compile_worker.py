from jubensha.compiler.pipeline import compile_document
from jubensha.eval.harness import run_eval
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.jobs import CompileJobs, EvalJobs
from jubensha.storage.scripts import ScriptStore


def drain_compile_jobs(events: EventStore, jobs: CompileJobs, scripts: ScriptStore) -> None:
    while job := jobs.claim_next():
        try:
            filename, content = scripts.get_upload(job["upload_id"])
            draft = compile_document(filename, content, events)
            jobs.finish(job["job_id"], script_id=scripts.save_draft(draft, job["upload_id"]))
        except Exception as exc:
            jobs.finish(job["job_id"], error=str(exc)[:1000])


def drain_eval_jobs(events: EventStore, jobs: EvalJobs, scripts: ScriptStore,
                    fixture: Script) -> None:
    while job := jobs.claim_next():
        try:
            script = (fixture if job["script_id"] == fixture.script_id
                      else scripts.load_published(job["script_id"]))
            report = run_eval(script, events, games_per_persona=job["games_per_persona"],
                              live_model=bool(job["live_model"]))
            jobs.finish(job["job_id"], run_id=report.run_id,
                        metrics=report.metrics.model_dump())
        except Exception as exc:
            jobs.finish(job["job_id"], error=str(exc)[:1000])
