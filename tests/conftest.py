import json
import uuid
from pathlib import Path

import psycopg
import pytest

from jubensha.schema.ir import Script
from jubensha.schema.state import GameState, SeatState
from jubensha.storage import db as pg
from jubensha.storage.events import EventStore


@pytest.fixture(autouse=True)
def default_generation_mode(monkeypatch):
    """测试锁定代码默认行为，不跟随本地 .env 的实验性开关。"""
    monkeypatch.setenv("NPC_GENERATION_MODE", "grounded")
    monkeypatch.setenv("CONTEXT_MODE", "full")


@pytest.fixture(autouse=True)
def isolated_schema():
    """每个测试独占一个 PostgreSQL schema，结束后整库清理。"""
    name = f"t_{uuid.uuid4().hex[:12]}"
    dsn = pg.resolve_dsn()
    previous = EventStore.schema_override
    EventStore.schema_override = name
    try:
        yield name
    finally:
        EventStore.schema_override = previous
        with psycopg.connect(dsn, autocommit=True) as connection:
            connection.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')


@pytest.fixture
def script():
    return Script.model_validate(json.loads(Path("fixtures/wugang_01.json").read_text(encoding="utf-8")))


@pytest.fixture
def state(script):
    return GameState(game_id="test", script_id=script.script_id, act_id=script.acts[0].act_id,
                     seats={"seat_1": SeatState(seat_id="seat_1")})
