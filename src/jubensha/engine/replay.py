from jubensha.engine.memory import visible_events
from jubensha.engine.perception import PerceptionView, build_perception
from jubensha.schema.events import GameEvent
from jubensha.schema.ir import Script
from jubensha.schema.state import GameState
from jubensha.storage.events import EventStore


def replay_at(script: Script, store: EventStore, game_id: str, seq: int,
              perspective: str) -> tuple[GameState, list[GameEvent], PerceptionView | None]:
    state = store.load(game_id, script.acts[0].search_points_budget, up_to_seq=seq)
    if perspective not in state.seats and perspective not in script.characters:
        raise ValueError("unknown replay perspective")
    events = visible_events(store.events(game_id, up_to_seq=seq), perspective)
    perception = build_perception(script, state, perspective) if perspective in script.characters else None
    return state, events, perception


def reference_evidence(script: Script) -> list[str]:
    culprits = {role_id for role_id, character in script.characters.items() if character.is_culprit}
    relevant_events = {event.event_id for event in script.truth_events
                       if culprits.intersection(event.actor_ids)}
    relevant_secrets = {secret.secret_id for secret in script.secrets.values()
                        if secret.owner_role_id in culprits}
    selected = {clue.clue_id for clue in script.clues.values()
                if relevant_events.intersection(clue.reveals_event_ids)
                or relevant_secrets.intersection(clue.reveals_secret_ids)}
    pending = list(selected)
    while pending:
        clue_id = pending.pop()
        for prerequisite in script.clues[clue_id].prerequisites:
            if prerequisite in script.clues and prerequisite not in selected:
                selected.add(prerequisite)
                pending.append(prerequisite)
    return [clue_id for clue_id in script.clues if clue_id in selected]
