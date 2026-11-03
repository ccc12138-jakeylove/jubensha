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
    public_clues: set[str] = set()
    location_counts: dict[str, int] = {}
    bundle_locations: dict[str, str] = {}
    for event in events:
        if event.type in (EventType.NPC_SPEECH, EventType.CLAIM):
            role_id = event.payload.get("role_id")
            knowledge = script.knowledge.get(role_id)
            citations = event.payload.get("evidence_ids", [])
            if knowledge is None:
                failures.append(f"unknown NPC role at seq {event.seq}")
            elif any(reference not in
                     (set(knowledge.knows_event_ids) | set(knowledge.knows_clue_ids) | public_clues
                      | {item.statement_id for item in knowledge.statements if item.approved})
                     for reference in citations):
                failures.append(f"unauthorized NPC citation at seq {event.seq}")
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
            bundle_id = event.payload.get("bundle_id")
            if bundle_id and script.search_mode == "location_bundle":
                expected_cost = 1 if bundle_id not in bundle_locations else 0
                if bundle_id in bundle_locations and bundle_locations[bundle_id] != clue.location_id:
                    failures.append(f"bundle spans locations at seq {event.seq}")
                bundle_locations[bundle_id] = clue.location_id
            else:
                expected_cost = clue.search_cost
            if event.payload.get("search_cost") != expected_cost:
                failures.append(f"incorrect search cost for {clue_id}")
            if phase != Phase.SEARCH:
                failures.append(f"clue outside search at seq {event.seq}")
            points -= event.payload.get("search_cost", 0)
            if points < 0:
                failures.append(f"search points overdrawn at seq {event.seq}")
            location_counts[clue.location_id] = location_counts.get(clue.location_id, 0) + 1
            if location_counts[clue.location_id] > script.locations[clue.location_id].capacity_per_act:
                failures.append(f"location capacity exceeded for {clue.location_id}")
            acquired.add(clue_id)
            if "*" in event.visible_to:
                public_clues.add(clue_id)
    return failures
