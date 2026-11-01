import json
from pathlib import Path

import pytest

from jubensha.schema.ir import Script
from jubensha.schema.state import GameState, SeatState


@pytest.fixture
def script():
    return Script.model_validate(json.loads(Path("fixtures/wugang_01.json").read_text(encoding="utf-8")))


@pytest.fixture
def state(script):
    return GameState(game_id="test", script_id=script.script_id, act_id=script.acts[0].act_id,
                     seats={"seat_1": SeatState(seat_id="seat_1")})
