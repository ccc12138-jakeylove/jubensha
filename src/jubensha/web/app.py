"""宣传页后端：只读展示数据 + 指认判定 + 预约登记。

设计约束：
- 不修改任何对局逻辑，只读取 Script（IR）与既有存储层；
- 指认结果由剧本真相（is_culprit）判定，真相字段不外泄给前端；
- 预约写入独立的 show_signups 表，与对局数据隔离。
"""

import os
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore

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
    """把 IR 压成宣传页需要的形状，刻意不含任何真相/私密字段。"""
    act = script.acts[0]

    # 时间线：只暴露「旁观者能听见/看见」的描述，真相事件的 action 一律不外泄，
    # 否则宣传页会直接写出凶手的作案过程。
    locations = script.locations
    timeline = []
    for event in sorted(script.truth_events, key=lambda item: item.t_start):
        visible = [text for text in event.observable if text.strip()]
        place = locations[event.location_id].display_name if event.location_id in locations else ""
        # 优先用「公开线索」描述这一刻：既具体又不泄露真相
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
            "act": "、".join(clue.act_available),
            "cost": clue.search_cost,
            "red_herring": clue.red_herring,
        })

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
        "timeline": timeline,
        "sessions": [{"id": key, "label": label} for key, label in SESSIONS.items()],
    }


def create_show_app(fixture_path: str | None = None, dsn: str | None = None) -> FastAPI:
    """构造宣传页应用。fixture 与数据库均可通过环境变量覆盖。"""
    fixture_file = Path(fixture_path or os.getenv("SCRIPT_FIXTURE", "fixtures/wugang_01.json"))
    script = Script.model_validate_json(fixture_file.read_text(encoding="utf-8"))
    store = EventStore(dsn or os.getenv("GAME_DB", "game.db"))
    show = build_show(script)

    app = FastAPI(title="雾港档案室", docs_url=None, redoc_url=None)

    @app.get("/api/show/script")
    def get_show() -> dict:
        return show

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
