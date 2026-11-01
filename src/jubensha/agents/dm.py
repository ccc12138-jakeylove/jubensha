from jubensha.schema.ir import Script
from jubensha.schema.state import GameState


def narrate(script: Script, state: GameState) -> str:
    act = next(a for a in script.acts if a.act_id == state.act_id)
    return act.public_narrative
