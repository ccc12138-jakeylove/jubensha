from jubensha.compiler.lint import lint_script
from jubensha.engine.board import owned_clue_ids
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import Script
from jubensha.schema.state import GameState


def analyze_recap(script: Script, state: GameState, events: list[GameEvent],
                  seat_id: str) -> dict:
    owned = owned_clue_ids(state, seat_id)
    reference = lint_script(script).solvability.optimal_path_clue_ids
    found_turns = {event.payload["clue_id"]: event.turn for event in events
                   if event.type == EventType.CLUE_FOUND
                   and event.payload.get("clue_id") in owned}
    submitted = set(state.vote_evidence_ids)
    return {
        "reference_clue_ids": reference,
        "found_clue_ids": [key for key in reference if key in owned],
        "missing_clue_ids": [key for key in reference if key not in owned],
        "not_submitted_clue_ids": [key for key in reference if key in owned and key not in submitted],
        "first_found_turn": found_turns,
        "requires_human_review": True,
    }
