from jubensha.schema.ir import Script
from jubensha.schema.state import GameState


class TruthStore:
    def __init__(self, script: Script):
        self.script = script

    def recap(self) -> dict:
        return {
            "culprits": [c.display_name for c in self.script.characters.values() if c.is_culprit],
            "timeline": [e.model_dump() for e in self.script.truth_events],
            "secrets": [s.model_dump() for s in self.script.secrets.values()],
        }


class PublicStore:
    def __init__(self, script: Script):
        self.script = script

    def view(self, state: GameState) -> dict:
        act = next(a for a in self.script.acts if a.act_id == state.act_id)
        return {
            "narrative": act.public_narrative,
            "characters": {key: value.public_profile for key, value in self.script.characters.items()},
            "clues": {key: self.script.clues[key].surface_text for key in state.public_clue_ids},
        }
