import json

from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import Script
from jubensha.schema.state import GameState


def owned_clue_ids(state: GameState, seat_id: str) -> set[str]:
    if seat_id not in state.seats:
        raise PermissionError("seat does not belong to this game")
    return set(state.public_clue_ids) | set(state.seats[seat_id].private_clue_ids)


def visible_relationships(script: Script, state: GameState, seat_id: str):
    owned = owned_clue_ids(state, seat_id)
    return [relation for relation in script.relationships
            if relation.is_public or owned.intersection(relation.evidence_clue_ids)]


def relationship_dot(script: Script, state: GameState, seat_id: str) -> str:
    lines = ["graph relationships {", "rankdir=LR;", "node [shape=box];"]
    for role_id, character in script.characters.items():
        lines.append(f"{json.dumps(role_id)} [label={json.dumps(character.display_name, ensure_ascii=False)}];")
    for relation in visible_relationships(script, state, seat_id):
        for role_id in (relation.from_role, relation.to_role):
            if role_id not in script.characters:
                lines.append(f"{json.dumps(role_id)} [label={json.dumps(role_id.replace('_', ' '))}];")
        lines.append(f"{json.dumps(relation.from_role)} -- {json.dumps(relation.to_role)} "
                     f"[label={json.dumps(relation.type)}];")
    lines.append("}")
    return "\n".join(lines)


def clue_dot(script: Script, state: GameState, seat_id: str) -> str:
    owned = owned_clue_ids(state, seat_id)
    lines = ["digraph clues {", "rankdir=LR;", "node [shape=box];"]
    for clue_id in sorted(owned):
        clue = script.clues[clue_id]
        lines.append(f"{json.dumps(clue_id)} [label={json.dumps(clue.display_name, ensure_ascii=False)}];")
        for prerequisite in clue.prerequisites:
            if prerequisite in owned:
                lines.append(f"{json.dumps(prerequisite)} -> {json.dumps(clue_id)};")
    lines.append("}")
    return "\n".join(lines)


def timeline_rows(events: list[GameEvent]) -> list[dict]:
    labels = {EventType.PLAYER_INPUT: "询问", EventType.NPC_SPEECH: "发言",
              EventType.CLUE_FOUND: "线索", EventType.VOTE: "指认"}
    return [{"回合": event.turn, "事件": labels[event.type],
             "内容": event.payload.get("text") or event.payload.get("clue_id")
             or event.payload.get("role_id") or ""}
            for event in events if event.type in labels]
