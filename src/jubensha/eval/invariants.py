from jubensha.engine.fsm import Phase, transition
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import Script


def check_invariants(script: Script, events: list[GameEvent]) -> list[str]:
    failures = []
    if [event.seq for event in events] != list(range(1, len(events) + 1)):
        failures.append("event sequence is not contiguous")
    act_by_id = {act.act_id: act for act in script.acts}
    act_id = min(script.acts, key=lambda act: act.order).act_id
    phase = Phase.ENTRY
    points = act_by_id[act_id].search_points_budget
    acquired: set[str] = set()
    location_counts: dict[str, int] = {}
    for event in events:
        if event.type == EventType.PHASE_CHANGE:
            target = Phase(event.payload["to"])
            try:
                transition(phase, target, last_act=(act_id == max(script.acts, key=lambda act: act.order).act_id))
            except ValueError:
                failures.append(f"illegal phase transition at seq {event.seq}")
            phase = target
            if "act_id" in event.payload:
                act_id = event.payload["act_id"]
                points = act_by_id[act_id].search_points_budget
                location_counts.clear()
        elif event.type == EventType.CLUE_FOUND:
            clue_id = event.payload["clue_id"]
            clue = script.clues.get(clue_id)
            if clue is None:
                failures.append(f"unknown clue at seq {event.seq}")
                continue
            if clue_id in acquired:
                failures.append(f"duplicate clue {clue_id}")
            if not set(clue.prerequisites).issubset(acquired):
                failures.append(f"missing prerequisite for {clue_id}")
            if event.payload.get("search_cost") != clue.search_cost:
                failures.append(f"incorrect search cost for {clue_id}")
            if phase != Phase.SEARCH:
                failures.append(f"clue outside search at seq {event.seq}")
            points -= clue.search_cost
            if points < 0:
                failures.append(f"search points overdrawn at seq {event.seq}")
            location_counts[clue.location_id] = location_counts.get(clue.location_id, 0) + 1
            if location_counts[clue.location_id] > script.locations[clue.location_id].capacity_per_act:
                failures.append(f"location capacity exceeded for {clue.location_id}")
            acquired.add(clue_id)
    return failures
