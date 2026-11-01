import json
import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from jubensha.agents.referee import judge_submission
from jubensha.compiler.pipeline import compile_document
from jubensha.engine.fsm import Phase
from jubensha.engine.loop import build_turn_graph, run_turn
from jubensha.engine.replay import replay_at
from jubensha.engine.world import TruthStore
from jubensha.eval.harness import run_eval
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
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


class EvalRequest(BaseModel):
    script_id: str | None = None
    games_per_persona: int = Field(default=5, ge=1, le=20)
    live_model: bool = False


def create_app(db_path: str | None = None, fixture_path: str | None = None) -> FastAPI:
    fixture = Script.model_validate_json(Path(fixture_path or os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json")).read_text(encoding="utf-8"))
    events = EventStore(db_path or os.getenv("GAME_DB", "game.db"))
    scripts = ScriptStore(events)
    scripts.register_fixture(fixture)
    api = FastAPI(title="剧本杀 V1")

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
            return selected_script(events.game_script_id(game_id))
        except KeyError as exc:
            raise HTTPException(404, "game not found") from exc

    def seat_state(game_id: str, seat_id: str):
        script = game_script(game_id)
        try:
            return events.load_for_seat(game_id, seat_id, script.acts[0].search_points_budget)
        except PermissionError as exc:
            raise HTTPException(403, str(exc)) from exc

    @api.post("/api/scripts")
    async def upload_script(file: UploadFile = File(...), authorized: bool = Form(...),
                            authorization: str | None = Header(default=None)):
        require_token(authorization)
        if not authorized:
            raise HTTPException(422, "script usage rights must be confirmed")
        content = await file.read()
        if len(content) > 10_000_000:
            raise HTTPException(413, "document exceeds 10 MB")
        return {"upload_id": scripts.save_upload(file.filename or "upload.txt", content)}

    @api.post("/api/scripts/{upload_id}/compile")
    def compile_script(upload_id: str, authorization: str | None = Header(default=None)):
        require_token(authorization)
        try:
            filename, content = scripts.get_upload(upload_id)
        except KeyError as exc:
            raise HTTPException(404, "upload not found") from exc
        try:
            draft = compile_document(filename, content, events)
            script_id = scripts.save_draft(draft)
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
    def create_game(body: GameCreate, authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = selected_script(body.script_id)
        game_id = uuid4().hex
        events.create_game(game_id, script.script_id, script.acts[0].act_id)
        return {"game_id": game_id, "script_id": script.script_id}

    @api.get("/api/games/{game_id}")
    def get_game(game_id: str, seat_id: str = "seat_1",
                 authorization: str | None = Header(default=None)):
        require_token(authorization)
        return seat_state(game_id, seat_id).model_dump(mode="json")

    @api.post("/api/games/{game_id}/turns")
    def post_turn(game_id: str, body: TurnRequest, stream: bool = False,
                  authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        seat_state(game_id, body.seat_id)
        data = body.model_dump(exclude_none=True, exclude={"seat_id"})
        data.update(game_id=game_id, actor_seat_id=body.seat_id)
        try:
            result = run_turn(build_turn_graph(script, events), events, script, data)
        except (ValueError, KeyError, PermissionError) as exc:
            raise HTTPException(422, str(exc)) from exc
        payload = {"reply": result.get("reply", ""),
                   "state": seat_state(game_id, body.seat_id).model_dump(mode="json")}
        if stream:
            return StreamingResponse(iter([f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"]),
                                     media_type="text/event-stream")
        return payload

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
                   perspective: str | None = None, authorization: str | None = Header(default=None)):
        require_token(authorization)
        script = game_script(game_id)
        current = seat_state(game_id, seat_id)
        if current.phase not in (Phase.RECAP, Phase.END):
            raise HTTPException(403, "replay unlocks after recap")
        last_seq = len(events.events(game_id))
        point = last_seq if seq is None else max(0, min(seq, last_seq))
        try:
            _, visible, perception = replay_at(script, events, game_id, point,
                                               perspective or seat_id)
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
