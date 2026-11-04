"""对外站点：宣传页 + 可直接对局的前端，后端复用既有对局 API。

设计约束：
- 对局逻辑完全复用 `jubensha.api.app.create_app`，本文件不重写任何回合规则；
- 只额外提供三个展示接口（剧本公开展示数据、指认判定、预约登记）与静态页面托管；
- 预约写入独立的 show_signups 表，与对局数据隔离。
"""

import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from fastapi.responses import FileResponse
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


class AccuseRequest(BaseModel):
    suspect_id: str


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
    """把 IR 压成前端需要的形状，刻意不含任何真相/私密字段。"""
    act = script.acts[0]
    locations = script.locations

    # 时间线：只用「公开线索」描述每一刻，真相事件的 action 一律不外泄
    timeline = []
    for event in sorted(script.truth_events, key=lambda item: item.t_start):
        visible = [text for text in event.observable if text.strip()]
        place = locations[event.location_id].display_name if event.location_id in locations else ""
        evidence = [script.clues[cid] for cid in event.evidence_clue_ids if cid in script.clues]
        if evidence:
            title = evidence[0].display_name
            detail = "　".join(clue.surface_text.strip().rstrip("。；") + "。" for clue in evidence[:2])
        elif visible:
            title = visible[0]
            detail = "；".join(visible[1:])
        else:
            title = place or "记录缺失"
            detail = ""
        timeline.append({
            "id": event.event_id,
            "offset": event.t_start,
            "title": title,
            "detail": detail,
            "place": place,
        })

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

    clues = []
    for clue_id, clue in script.clues.items():
        clues.append({
            "clue_id": clue_id,
            "name": clue.display_name,
            "text": clue.surface_text,
            "location": locations[clue.location_id].display_name if clue.location_id in locations else "",
            "location_id": clue.location_id,
            "act": "、".join(clue.act_available),
            "cost": clue.search_cost,
            "red_herring": clue.red_herring,
        })

    # 搜证地点：宣传页与对局台共用，只暴露名字与容量
    scenes = [
        {
            "id": location.location_id,
            "name": location.display_name,
            "capacity": getattr(location, "capacity", None),
            "clue_count": sum(1 for clue in script.clues.values() if clue.location_id == location.location_id),
        }
        for location in locations.values()
    ]

    return {
        "script_id": script.script_id,
        "title": script.title,
        "subtitle": f"{script.tone}的一夜，{act.title}",
        "tagline": "五个人的证词互相咬合，只有一个人的时间线永远对不上。",
        "genre": script.genre,
        "tone": script.tone,
        "difficulty": script.difficulty,
        "seat_range": list(script.seat_range),
        "act_title": act.title,
        "act_narrative": act.public_narrative,
        "dossier_no": f"{script.script_id.upper()}-{act.act_id}",
        "characters": characters,
        "clues": clues,
        "locations": scenes,
        "timeline": timeline,
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
    show = build_show(script)

    @app.get("/api/show/script")
    def get_show() -> dict:
        return show

    @app.get("/api/show/search-options")
    def search_options(game_id: str, location_id: str, seat_id: str = "seat_1") -> dict:
        """搜证候选：复用引擎的 available_clues，前端只负责展示与选择。

        规则（前置线索、地点容量、剩余点数）全部由引擎计算，本接口不重复实现。
        """
        try:
            script_id = store.game_script_id(game_id)
            state = store.load_for_seat(game_id, seat_id, script.acts[0].search_points_budget)
        except KeyError as exc:
            raise HTTPException(404, "对局或座位不存在") from exc
        game_script = script if script_id == script.script_id else ScriptStore(store).load_playable(script_id)
        location = game_script.locations.get(location_id)
        candidates = available_clues(game_script, state, location_id, seat_id)
        used = state.search_counts.get(location_id, 0)
        capacity = getattr(location, "capacity_per_act", 0) if location else 0
        return {
            "mode": game_script.search_mode,
            "location": location.display_name if location else "",
            "remaining": max(0, capacity - used),
            "options": [
                {
                    "clue_id": clue.clue_id,
                    "label": clue.search_label or clue.display_name,
                    "cost": clue.search_cost,
                }
                for clue in candidates
            ],
        }

    @app.post("/api/show/accuse")
    def accuse(payload: AccuseRequest) -> dict:
        suspect = script.characters.get(payload.suspect_id)
        if suspect is None:
            raise HTTPException(404, "嫌疑人不在名单内")
        culprit = next((role for role in script.characters.values() if role.is_culprit), None)
        if culprit is None:
            raise HTTPException(409, "该剧本未标注凶手")
        if suspect.role_id == culprit.role_id:
            evidence = "、".join(
                clue.display_name for clue in script.clues.values()
                if any(event.event_id in clue.reveals_event_ids for event in script.truth_events
                       if any(actor == culprit.role_id for actor in event.actor_ids))
            ) or "现场遗留物"
            return {
                "correct": True,
                "message": f"证据链闭合：{suspect.display_name} 就是这起案子的凶手。",
                "truth": f"关键物证：{evidence}",
            }
        return {
            "correct": False,
            "message": f"{suspect.display_name} 的时间线能自洽，至少这一刀不是他/她下的。",
            "truth": "",
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
