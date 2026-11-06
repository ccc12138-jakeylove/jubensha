"""对外站点：宣传页 + 可直接对局的前端，后端复用既有对局 API。

设计约束：
- 对局逻辑完全复用 `jubensha.api.app.create_app`，本文件不重写任何回合规则；
- 只额外提供三个展示接口（剧本公开展示数据、指认判定、预约登记）与静态页面托管；
- 预约写入独立的 show_signups 表，与对局数据隔离。
"""

import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jubensha.api.app import create_app as create_game_api
from jubensha.engine.search import available_clues
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore

# 前端构建产物目录：<项目根>/frontend/dist
DIST_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"

SESSIONS = {
    "fri-1930": "周五 19:30 · 首场",
    "sat-1400": "周六 14:00 · 下午场",
    "sat-1930": "周六 19:30 · 夜场",
}


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    phone: str = Field(min_length=11, max_length=11)
    session: str


def _identity(profile: str) -> str:
    """从公开简介里截出身份标签（第一个分句），过长则截断。"""
    for separator in ("，", "。", "；", ","):
        if separator in profile:
            head = profile.split(separator)[0]
            break
    else:
        head = profile
    return head[:14]


def build_show(script: Script) -> dict:
    """Only return information available before a game begins."""
    act = script.acts[0]
    locations = script.locations

    characters = []
    for role_id, role in script.characters.items():
        characters.append({
            "role_id": role_id,
            "name": role.display_name,
            "identity": _identity(role.public_profile),
            "profile": role.public_profile,
            "style": role.persona_style,
            # 只给数量，不给内容，避免宣传页剧透
            "secret_count": len(role.secret_ids),
            "goal_count": len(role.private_goals),
        })

    # 搜证地点：宣传页与对局台共用，只暴露名字与容量
    scenes = [
        {
            "id": location.location_id,
            "name": location.display_name,
            "capacity": location.capacity_per_act,
            "clue_count": sum(1 for clue in script.clues.values()
                              if clue.location_id == location.location_id
                              and act.act_id in clue.act_available),
        }
        for location in locations.values()
        if act.act_id in location.act_availability
    ]

    return {
        "script_id": script.script_id,
        "title": script.title,
        "subtitle": f"{script.tone}的一夜，{act.title}",
        "tagline": act.public_narrative,
        "genre": script.genre,
        "tone": script.tone,
        "difficulty": script.difficulty,
        "seat_range": list(script.seat_range),
        "act_title": act.title,
        "act_narrative": act.public_narrative,
        "dossier_no": f"{script.script_id.upper()}-{act.act_id}",
        "characters": characters,
        "locations": scenes,
        "sessions": [{"id": key, "label": label} for key, label in SESSIONS.items()],
    }


def create_show_app(fixture_path: str | None = None, dsn: str | None = None):
    """构造站点：直接复用对局 API 应用，再叠加展示接口与静态页面。"""
    fixture_file = Path(fixture_path or os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"))
    script = Script.model_validate_json(fixture_file.read_text(encoding="utf-8"))
    database = dsn or os.getenv("GAME_DB", "game.db")

    # 复用既有对局应用（路由、异常格式、lifespan 全部继承）
    app = create_game_api(db_path=database, fixture_path=str(fixture_file))
    store = EventStore(database)
    scripts = ScriptStore(store)

    admin_prefixes = ("/api/scripts", "/api/v2/scripts", "/api/v2/compile-jobs",
                      "/api/v2/eval-runs", "/api/evals")

    @app.middleware("http")
    async def protect_author_api(request: Request, call_next):
        path = request.url.path
        if any(path == prefix or path.startswith(prefix + "/") for prefix in admin_prefixes):
            token = os.getenv("API_TOKEN") or os.getenv("AUTHOR_TOKEN")
            if not token:
                return JSONResponse({"detail": "author access is not configured"}, status_code=503)
            if request.headers.get("authorization") != f"Bearer {token}":
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        return await call_next(request)

    def selected_script(script_id: str | None) -> Script:
        if not script_id or script_id == script.script_id:
            return script
        try:
            return scripts.load_published(script_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "剧本未发布") from exc

    def game_script(game_id: str) -> Script:
        try:
            script_id = store.game_script_id(game_id)
            return script if script_id == script.script_id else scripts.load_playable(script_id)
        except (KeyError, ValueError) as exc:
            raise HTTPException(404, "对局不存在") from exc

    @app.get("/api/show/scripts")
    def list_show_scripts() -> list[dict]:
        published = scripts.list_scripts(status="published")
        return [{"script_id": script.script_id, "title": script.title},
                *({"script_id": row["script_id"], "title": row["title"]}
                  for row in published if row["script_id"] != script.script_id)]

    @app.get("/api/show/script")
    def get_show(script_id: str | None = None) -> dict:
        return build_show(selected_script(script_id))

    @app.get("/api/show/games/{game_id}/act")
    def get_game_act(game_id: str, seat_id: str = "seat_1") -> dict:
        game = game_script(game_id)
        try:
            state = store.load_for_seat(game_id, seat_id, game.acts[0].search_points_budget)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, "对局或座位不存在") from exc
        act = next(item for item in game.acts if item.act_id == state.act_id)
        return {
            "act_id": act.act_id, "title": act.title,
            "narrative": act.public_narrative,
            "requires_vote": act.requires_vote,
            "is_final": act.act_id == max(game.acts, key=lambda item: item.order).act_id,
            "locations": [
                {"id": location.location_id, "name": location.display_name,
                 "capacity": location.capacity_per_act,
                 "clue_count": sum(1 for clue in game.clues.values()
                                   if clue.location_id == location.location_id
                                   and act.act_id in clue.act_available)}
                for location in game.locations.values()
                if act.act_id in location.act_availability],
        }

    @app.get("/api/show/search-options")
    def search_options(game_id: str, location_id: str, seat_id: str = "seat_1") -> dict:
        """搜证候选：复用引擎的 available_clues，前端只负责展示与选择。

        规则（前置线索、地点容量、剩余点数）全部由引擎计算，本接口不重复实现。
        """
        try:
            game = game_script(game_id)
            state = store.load_for_seat(game_id, seat_id, game.acts[0].search_points_budget)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(404, "对局或座位不存在") from exc
        location = game.locations.get(location_id)
        candidates = available_clues(game, state, location_id, seat_id)
        used = state.search_counts.get(location_id, 0)
        capacity = getattr(location, "capacity_per_act", 0) if location else 0
        return {
            "mode": game.search_mode,
            "location": location.display_name if location else "",
            "remaining": max(0, capacity - used),
            "options": [
                {
                    "clue_id": clue.clue_id,
                    "label": clue.search_label or clue.display_name,
                    "cost": 1 if game.search_mode == "location_bundle" else clue.search_cost,
                }
                for clue in candidates
            ],
        }

    @app.post("/api/show/signup")
    def signup(payload: SignupRequest) -> dict:
        name = payload.name.strip()
        phone = payload.phone.strip()
        if not name:
            raise HTTPException(422, "请填写称呼")
        if not (len(phone) == 11 and phone.isdigit()):
            raise HTTPException(422, "请填写 11 位手机号")
        if payload.session not in SESSIONS:
            raise HTTPException(422, "场次无效")
        ticket = uuid4().hex[:8].upper()
        with store.connect() as db:
            db.execute(
                "INSERT INTO show_signups (name,phone,session,ticket) VALUES (%s,%s,%s,%s)",
                (name, phone, payload.session, ticket))
        return {
            "ok": True,
            "name": name,
            "session": payload.session,
            "session_label": SESSIONS[payload.session],
            "ticket": ticket,
        }

    # 静态资源：构建产物存在时提供页面；未构建则返回可读提示
    assets = DIST_DIR / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def index():
        page = DIST_DIR / "index.html"
        if not page.is_file():
            raise HTTPException(
                503,
                "前端尚未构建：执行 `cd frontend && npm install && npm run build` 后重试",
            )
        return FileResponse(page)

    return app


app = create_show_app()
