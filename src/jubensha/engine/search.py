from jubensha.schema.ir import Clue, Script
from jubensha.schema.state import GameState


def available_clues(script: Script, state: GameState, location_id: str) -> list[Clue]:
    location = script.locations.get(location_id)
    if location is None or not location.searchable or state.act_id not in location.act_availability:
        return []
    if state.search_counts.get(location_id, 0) >= location.capacity_per_act:
        return []
    seat = next(iter(state.seats.values()))
    owned = set(state.public_clue_ids) | set(seat.private_clue_ids)
    return [clue for clue in script.clues.values()
            if clue.location_id == location_id and state.act_id in clue.act_available
            and clue.clue_id not in owned and set(clue.prerequisites).issubset(owned)
            and clue.search_cost <= seat.search_points]


def select_clue(script: Script, state: GameState, location_id: str, clue_id: str) -> Clue:
    candidates = available_clues(script, state, location_id)
    for clue in candidates:
        if clue.clue_id == clue_id:
            return clue
    raise ValueError("线索不可搜查：请检查地点、前置线索、容量或剩余点数")
