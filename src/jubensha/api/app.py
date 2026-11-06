import json
import os
import time
from hashlib import sha256
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from queue import Queue
from threading import Thread
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from jubensha.agents.referee import judge_submission
from jubensha.compiler.pipeline import compile_document
from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.replay import replay_at
from jubensha.engine.recap import analyze_recap
from jubensha.engine.world import TruthStore
from jubensha.eval.harness import run_eval
from jubensha.schema.ir import Script
from jubensha.services.compile_worker import drain_compile_jobs, drain_eval_jobs
from jubensha.storage.events import EventStore
from jubensha.storage.jobs import CompileJobs, EvalJobs
from jubensha.storage.streams import TurnStreams
from jubensha.storage.scripts import ScriptStore


class GameCreate(BaseModel):
    script_id: str | None = None


class TurnRequest(BaseModel):
    action: str
    seat_id: str = "seat_1"
    text: str = ""
    role_id: str | None = None
    location_id: str | None = None
    clue_id: str | None = None
    motive: str = ""
    evidence_ids: list[str] = Field(default_factory=list)


class IRUpdate(BaseModel):
    ir: dict


class RightsConfirmation(BaseModel):
    authorized: bool
    rights_source: str
    rights_contact: str = ""


class EvalRequest(BaseModel):
    script_id: str | None = None
    games_per_persona: int = Field(default=5, ge=1, le=20)
    live_model: bool = False


class CompileJobRequest(BaseModel):
    upload_id: str


def create_app(db_path: str | None = None, fixture_path: str | None = None) -> FastAPI:
    fixture = Script.model_validate_json(Path(fixture_path or os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json")).read_text(encoding="utf-8"))
    events = EventStore(db_path or os.getenv("GAME_DB", "game.db"))
    scripts = ScriptStore(events)
    jobs = CompileJobs(events)
    eval_jobs = EvalJobs(events)
    streams = TurnStreams(events)
    scripts.register_fixture(fixture)
    worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="compile")
    eval_worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="eval")

    @asynccontextmanager
    async def lifespan(_api: FastAPI):
        worker.submit(drain_compile_jobs, events, jobs, scripts)
        eval_worker.submit(drain_eval_jobs, events, eval_jobs, scripts, fixture)
        yield
        worker.shutdown(wait=False, cancel_futures=True)
        eval_worker.shutdown(wait=False, cancel_futures=True)

    api = FastAPI(title="剧本杀 V2", lifespan=lifespan)

    @api.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if not request.url.path.startswith("/api/v2/"):
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
        message = str(exc.detail)
        code = ("SCRIPT_NOT_PUBLISHED" if "not published" in message or "not playable" in message
                else "QUOTA_EXCEEDED" if exc.status_code == 429
                else "LLM_UNAVAILABLE" if "LLM_MODEL" in message
                else "VALIDATION_ERROR" if exc.status_code in (409, 422)
                else "NOT_FOUND" if exc.status_code == 404 else "ACCESS_DENIED")
        return JSONResponse({"error": {"code": code, "message": message,
                                        "detail": {}, "request_id": uuid4().hex}},
                            status_code=exc.status_code)

    @api.exception_handler(RequestValidationError)
    async def request_error(request: Request, exc: RequestValidationError):
        detail = jsonable_encoder(exc.errors())
        if not request.url.path.startswith("/api/v2/"):
            return JSONResponse({"detail": detail}, status_code=422)
        return JSONResponse({"error": {"code": "VALIDATION_ERROR", "message": "request validation failed",
                                        "detail": {"fields": detail}, "request_id": uuid4().hex}},
                            status_code=422)

    def require_token(authorization: str | None):
        token = os.getenv("API_TOKEN")
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "unauthorized")

    def selected_script(script_id: str | None) -> Script:
        if not script_id or script_id == fixture.script_id:
            return fixture
        try:
            return scripts.load_published(script_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, str(exc)) from exc

    def game_script(game_id: str) -> Script:
        try:
            script_id = events.game_script_id(game_id)
            return fixture if script_id == fixture.script_id else scripts.load_playable(script_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "game not found") from exc

    def seat_state(game_id: str, seat_id: str):
        script = game_script(game_id)
        try:
            return events.load_for_seat(game_id, seat_id, script.acts[0].search_points_budget)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @api.post("/api/scripts")
    async def upload_script(file: UploadFile = File(...), authorized: bool = Form(...),
                            rights_source: str = Form(default="author confirmed"),
                            rights_contact: str = Form(default=""),
                            authorization: str | None = Header(default=None)):
        require_token(authorization)
        if not authorized:
            raise HTTPException(422, "script usage rights must be confirmed")
        content = await file.read()
        if len(content) > 10_000_000:
            raise HTTPException(413, "document exceeds 10 MB")
        try:
            upload_id = scripts.save_upload(file.filename or "upload.txt", content,
                                            rights_source, rights_contact)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"upload_id": upload_id}

    @api.post("/api/v2/scripts")
    async def upload_script_v2(file: UploadFile = File(...), authorized: bool = Form(...),
                               rights_source: str = Form(...),
                               rights_contact: str = Form(default=""),
                               authorization: str | None = Header(default=None)):
        return await upload_script(file, authorized, rights_source, rights_contact, authorization)

    @api.post("/api/v2/compile-jobs", status_code=202)
    def create_compile_job(body: CompileJobRequest,
                           idempotency_key: str | None = Header(default=None),
                           authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.get_upload(body.upload_id)
            job = jobs.create(body.upload_id, idempotency_key)
        except KeyError as exc:
            raise HTTPException(404, "upload not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        worker.submit(drain_compile_jobs, events, jobs, scripts)
        return job

    @api.get("/api/v2/compile-jobs/{job_id}")
    def get_compile_job(job_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            return jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "job not found") from exc

    @api.post("/api/v2/compile-jobs/{job_id}/retry", status_code=202)
    def retry_compile_job(job_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            job = jobs.retry(job_id)
        except KeyError as exc:
            raise HTTPException(404, "job not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        worker.submit(drain_compile_jobs, events, jobs, scripts)
        return job

    @api.post("/api/v2/eval-runs", status_code=202)
    def create_eval_job(body: EvalRequest,
                        idempotency_key: str | None = Header(default=None),
                        authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = selected_script(body.script_id)
        try:
            job = eval_jobs.create(script.script_id, body.games_per_persona,
                                   body.live_model, idempotency_key)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        eval_worker.submit(drain_eval_jobs, events, eval_jobs, scripts, fixture)
        return job

    @api.get("/api/v2/eval-runs/{job_id}")
    def get_eval_job(job_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            return eval_jobs.get(job_id)
        except KeyError as exc:
            raise HTTPException(404, "evaluation not found") from exc

    @api.post("/api/v2/eval-runs/{job_id}/retry", status_code=202)
    def retry_eval_job(job_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            job = eval_jobs.retry(job_id)
        except KeyError as exc:
            raise HTTPException(404, "evaluation not found") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        eval_worker.submit(drain_eval_jobs, events, eval_jobs, scripts, fixture)
        return job

    @api.get("/api/v2/scripts")
    def list_scripts_v2(status: str | None = None, genre: str | None = None,
                        difficulty: int | None = None,
                        authorization: str | None = Header(default=None)):
        require_token(authorization)
        return scripts.list_scripts(status=status, genre=genre, difficulty=difficulty)

    @api.get("/api/v2/scripts/{script_id}/versions")
    def script_versions_v2(script_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.get_draft(script_id)
        except KeyError as exc:
            raise HTTPException(404, "script not found") from exc
        return {"versions": scripts.versions(script_id), "revisions": scripts.revisions(script_id)}

    @api.post("/api/v2/scripts/{script_id}/archive")
    def archive_script_v2(script_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.archive(script_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"script_id": script_id, "status": "archived"}

    @api.post("/api/v2/scripts/{script_id}/rights")
    def confirm_script_rights_v2(script_id: str, body: RightsConfirmation,
                                 authorization: str | None = Header(default=None)):
        require_token(authorization)
        if not body.authorized:
            raise HTTPException(422, "script usage rights must be confirmed")
        try:
            draft = scripts.get_draft(script_id)
            if not draft["source_upload_id"]:
                raise ValueError("script has no uploaded source")
            scripts.confirm_rights(draft["source_upload_id"], body.rights_source,
                                   body.rights_contact)
        except KeyError as exc:
            raise HTTPException(404, "script or upload not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        scripts.audit("author", "confirm_rights", script_id, body.rights_source)
        return {"script_id": script_id, "rights_confirmed": True}

    @api.delete("/api/v2/scripts/{script_id}")
    def delete_draft_v2(script_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.delete_draft(script_id)
        except KeyError as exc:
            raise HTTPException(404, "script not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"script_id": script_id, "status": "deleted"}

    @api.post("/api/scripts/{upload_id}/compile")
    def compile_script(upload_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            filename, content = scripts.get_upload(upload_id)
        except KeyError as exc:
            raise HTTPException(404, "upload not found") from exc
        try:
            draft = compile_document(filename, content, events)
            script_id = scripts.save_draft(draft, upload_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"script_id": script_id, "valid": draft.valid,
                "review_items": len(draft.review_items)}

    @api.get("/api/scripts/{script_id}/review")
    def review_script(script_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            draft = scripts.get_draft(script_id)
        except KeyError as exc:
            raise HTTPException(404, "script not found") from exc
        return {"script_id": script_id, "status": draft["status"], "ir": draft["ir"],
                "source_text": draft["source_text"],
                "items": [{"item_id": item_id, "item": item.model_dump(), "resolved": resolved}
                          for item_id, item, resolved in scripts.reviews(script_id)]}

    @api.post("/api/scripts/{script_id}/review/{item_id}/resolve")
    def resolve_review(script_id: str, item_id: int,
                       authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.resolve(script_id, item_id)
        except KeyError as exc:
            raise HTTPException(404, "review item not found") from exc
        return {"item_id": item_id, "resolved": True}

    @api.patch("/api/scripts/{script_id}/ir")
    def update_script(script_id: str, body: IRUpdate, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            scripts.update_ir(script_id, json.dumps(body.ir, ensure_ascii=False))
        except KeyError as exc:
            raise HTTPException(404, "script not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"script_id": script_id, "status": "draft"}

    @api.post("/api/scripts/{script_id}/publish")
    def publish_script(script_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            script = scripts.publish(script_id)
        except KeyError as exc:
            raise HTTPException(404, "script not found") from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return {"script_id": script.script_id, "status": "published"}

    @api.post("/api/games")
    def create_game(body: GameCreate, authorization: str | None = Header(default=None),
                    idempotency_key: str | None = Header(default=None)):
        require_token(authorization)
        script = selected_script(body.script_id)
        if idempotency_key:
            try:
                game_id = events.create_game_idempotent(script.script_id, script.acts[0].act_id,
                                                        idempotency_key)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
        else:
            game_id = uuid4().hex
            events.create_game(game_id, script.script_id, script.acts[0].act_id)
        return {"game_id": game_id, "script_id": script.script_id}

    @api.post("/api/v2/games")
    def create_game_v2(body: GameCreate, authorization: str | None = Header(default=None),
                       idempotency_key: str | None = Header(default=None)):
        return create_game(body, authorization, idempotency_key)

    @api.get("/api/games/{game_id}")
    def get_game(game_id: str, seat_id: str = "seat_1",
                 authorization: str | None = Header(default=None)):
        require_token(authorization)
        return seat_state(game_id, seat_id).model_dump(mode="json")

    @api.post("/api/games/{game_id}/turns")
    def post_turn(game_id: str, body: TurnRequest, stream: bool = False,
                  authorization: str | None = Header(default=None),
                  idempotency_key: str | None = Header(default=None),
                  last_event_id: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        seat_state(game_id, body.seat_id)
        data = body.model_dump(exclude_none=True, exclude={"seat_id"})
        data.update(game_id=game_id, actor_seat_id=body.seat_id)
        if stream and idempotency_key:
            try:
                cursor = int(last_event_id or "0")
                if cursor < 0:
                    raise ValueError("negative event id")
            except ValueError as exc:
                raise HTTPException(422, "Last-Event-ID must be a nonnegative integer") from exc
            request_hash = sha256(body.model_dump_json().encode("utf-8")).hexdigest()
            try:
                fresh = streams.begin(game_id, idempotency_key, body.seat_id, request_hash)
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from exc
            if fresh:
                def run_persisted():
                    def observer(kind: str, node: str):
                        streams.append(game_id, idempotency_key, kind, {"node": node})
                    try:
                        result = run_turn(build_turn_graph(script, events, observer), events,
                                          script, data)
                        reply = result.get("reply", "")
                        for start in range(0, len(reply), 32):
                            streams.append(game_id, idempotency_key, "token",
                                           {"text": reply[start:start + 32]})
                        streams.append(game_id, idempotency_key, "done",
                                       {"reply": reply,
                                        "state": seat_state(game_id, body.seat_id).model_dump(mode="json")})
                    except Exception as exc:
                        streams.append(game_id, idempotency_key, "error",
                                       {"code": "VALIDATION_ERROR", "message": str(exc)})
                Thread(target=run_persisted, daemon=True).start()
            def stream_persisted():
                seen = cursor
                while True:
                    updates = streams.after(game_id, idempotency_key, seen)
                    for item in updates:
                        seen = item["seq"]
                        yield f"id: {seen}\nevent: {item['kind']}\ndata: {json.dumps(item['payload'], ensure_ascii=False)}\n\n"
                        if item["kind"] in ("done", "error"):
                            return
                    status = streams.status(game_id, idempotency_key)
                    if status == "interrupted":
                        yield f"event: error\ndata: {json.dumps({'code': 'INTERRUPTED', 'message': 'turn was interrupted'})}\n\n"
                        return
                    if status in ("completed", "failed"):
                        # The terminal event and status commit together, but the earlier
                        # after() read may have raced that commit. Drain it next loop.
                        continue
                    time.sleep(0.1)
            return StreamingResponse(stream_persisted(), media_type="text/event-stream")
        if stream:
            def stream_events():
                queue: Queue[tuple[str, dict]] = Queue()
                def observer(kind: str, node: str):
                    queue.put((kind, {"node": node}))
                def run():
                    try:
                        result = run_turn(build_turn_graph(script, events, observer), events,
                                          script, data)
                        reply = result.get("reply", "")
                        for start in range(0, len(reply), 32):
                            queue.put(("token", {"text": reply[start:start + 32]}))
                        queue.put(("done", {"reply": reply,
                                            "state": seat_state(game_id, body.seat_id).model_dump(mode="json")}))
                    except Exception as exc:
                        queue.put(("error", {"code": "VALIDATION_ERROR", "message": str(exc)}))
                Thread(target=run, daemon=True).start()
                sequence = 0
                while True:
                    kind, payload = queue.get()
                    sequence += 1
                    yield f"id: {sequence}\nevent: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    if kind in ("done", "error"):
                        break
            return StreamingResponse(stream_events(), media_type="text/event-stream")
        try:
            result = run_turn(build_turn_graph(script, events), events, script, data)
        except (ValueError, KeyError, PermissionError) as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = {"reply": result.get("reply", ""),
                   "state": seat_state(game_id, body.seat_id).model_dump(mode="json")}
        return payload

    @api.post("/api/v2/games/{game_id}/turns")
    def post_turn_v2(game_id: str, body: TurnRequest, stream: bool = False,
                     authorization: str | None = Header(default=None),
                     idempotency_key: str | None = Header(default=None),
                     last_event_id: str | None = Header(default=None)):
        if stream and not idempotency_key:
            raise HTTPException(422, "Idempotency-Key is required for resumable stream")
        return post_turn(game_id, body, stream, authorization, idempotency_key, last_event_id)

    @api.get("/api/games/{game_id}/clues")
    def get_clues(game_id: str, seat_id: str = "seat_1",
                  authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        state = seat_state(game_id, seat_id)
        ids = list(dict.fromkeys(state.public_clue_ids + state.seats[seat_id].private_clue_ids))
        return [{"clue_id": key, "display_name": script.clues[key].display_name,
                 "surface_text": script.clues[key].surface_text} for key in ids]

    @api.post("/api/games/{game_id}/adjudicate")
    def adjudicate(game_id: str, body: TurnRequest,
                   authorization: str | None = Header(default=None)):
        require_token(authorization)
        if body.action != "vote":
            raise HTTPException(422, "action must be vote")
        post_turn(game_id, body, authorization=authorization)
        script = game_script(game_id)
        return judge_submission(script, seat_state(game_id, body.seat_id)).model_dump()

    @api.get("/api/games/{game_id}/replay")
    def get_replay(game_id: str, seq: int | None = None, seat_id: str = "seat_1",
                   perspective: str | None = None, authorization: str | None = Header(default=None),
                   x_author_token: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        current = seat_state(game_id, seat_id)
        if current.phase not in (Phase.RECAP, Phase.END):
            raise HTTPException(403, "replay unlocks after recap")
        last_seq = len(events.events(game_id))
        point = last_seq if seq is None else max(0, min(seq, last_seq))
        selected = perspective or seat_id
        if selected != seat_id:
            expected = os.getenv("AUTHOR_TOKEN")
            if not expected or x_author_token != expected:
                raise HTTPException(403, "author perspective requires author token")
            scripts.audit("author", "replay_perspective", game_id, f"{selected}@{point}")
        try:
            _, visible, perception = replay_at(script, events, game_id, point,
                                               selected)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        historic_seat = events.load_for_seat(game_id, seat_id, script.acts[0].search_points_budget,
                                            up_to_seq=point)
        return {"state": historic_seat.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in visible],
                "perception": perception.model_dump() if perception else None}

    @api.get("/api/games/{game_id}/report")
    def get_report(game_id: str, seat_id: str = "seat_1",
                   authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        state = seat_state(game_id, seat_id)
        if state.phase not in (Phase.RECAP, Phase.END):
            raise HTTPException(403, "report unlocks after recap")
        return {"judgment": judge_submission(script, state).model_dump(),
                "truth": TruthStore(script).recap()}

    @api.get("/api/v2/games/{game_id}/recap")
    def get_recap_v2(game_id: str, seat_id: str = "seat_1",
                     authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        state = seat_state(game_id, seat_id)
        if state.phase not in (Phase.RECAP, Phase.END):
            raise HTTPException(403, "recap unlocks after vote")
        return analyze_recap(script, state, events.events_for_seat(game_id, seat_id), seat_id)

    @api.post("/api/evals/run")
    def run_evaluation(body: EvalRequest, authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = selected_script(body.script_id)
        try:
            report = run_eval(script, events, games_per_persona=body.games_per_persona,
                              live_model=body.live_model)
        except RuntimeError as exc:
            raise HTTPException(422, str(exc)) from exc
        return report.model_dump(mode="json")

    return api


app = create_app()
