from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from jubensha.agents.dm import narrate
from jubensha.agents.npc import respond
from jubensha.engine.fsm import Phase, transition
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore


class TurnState(TypedDict, total=False):
    game_id: str
    action: str
    text: str
    role_id: str
    location_id: str
    motive: str
    evidence_ids: list[str]
    route: str
    reply: str
    clue_id: str
    target_phase: str


def build_turn_graph(script: Script, store: EventStore):
    def ingest_turn(data: TurnState) -> TurnState:
        data["text"] = data.get("text", "").strip()[:1000]
        return data

    def router(data: TurnState) -> TurnState:
        action = data["action"]
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        valid = {
            "begin": {Phase.ENTRY}, "read_done": {Phase.READ},
            "enter_search": {Phase.ACT_OPEN}, "leave_search": {Phase.SEARCH},
            "search": {Phase.SEARCH}, "talk": {Phase.ACT_OPEN},
            "enter_confront": {Phase.ACT_OPEN}, "leave_confront": {Phase.CONFRONT},
            "vote": {Phase.CONFRONT}, "recap": {Phase.VOTE}, "end": {Phase.RECAP},
        }
        if action not in valid or state.phase not in valid[action]:
            raise ValueError(f"action {action} is unavailable in {state.phase.value}")
        data["route"] = "npc" if action == "talk" else "search" if action == "search" else "dm"
        return data

    def npc_dispatch(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        if data["role_id"] not in script.characters:
            raise ValueError("unknown role")
        data["reply"] = respond(script, state, data["role_id"], data["text"],
                                store.events(data["game_id"]), store)
        return data

    def search_evidence(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        location = script.locations.get(data["location_id"])
        if location is None or not location.searchable or state.act_id not in location.act_availability:
            raise ValueError("location unavailable")
        owned = set(state.public_clue_ids) | set(next(iter(state.seats.values())).private_clue_ids)
        clue = next((c for c in script.clues.values() if c.location_id == location.location_id
                     and state.act_id in c.act_available and c.clue_id not in owned), None)
        if clue is None:
            data["reply"] = "这里没有新的线索。"
        else:
            data["clue_id"] = clue.clue_id
            data["reply"] = clue.surface_text
        return data

    def dm_narrate(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        phase_text = {
            "begin": "请阅读案件简报。", "read_done": "现在可以询问在场的人。",
            "enter_search": "请选择搜查地点。", "leave_search": "搜证结束，可以继续询问。",
            "enter_confront": "请提交指认、动机和证据。", "leave_confront": "继续询问吧。",
            "vote": "指认已记录。", "recap": "真相已揭晓。", "end": "本局结束。",
        }
        data["reply"] = narrate(script, state) if data["action"] == "begin" else phase_text[data["action"]]
        return data

    def leak_check(data: TurnState) -> TurnState:
        if data["route"] == "npc":
            # P0 guard: exact secret text and generated leak-surface phrases.
            forbidden = [phrase for surface in script.leak_surfaces.values()
                         for phrase in [surface.fact, *surface.paraphrases, *surface.implications]
                         if len(phrase) >= 6]
            if any(phrase in data["reply"] for phrase in forbidden):
                data["reply"] = "这事我不清楚。"
        return data

    def director_check(data: TurnState) -> TurnState:
        return data

    def memory_write(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        turn = state.turn + 1
        def append(kind: EventType, payload: dict, visible: list[str], actor: str = "system"):
            store.append(GameEvent(seq=0, game_id=state.game_id, actor_seat_id=actor,
                                   turn=turn, phase=state.phase, type=kind, payload=payload,
                                   visible_to=visible))
        if data["action"] == "talk":
            append(EventType.PLAYER_INPUT, {"text": data["text"], "role_id": data["role_id"]}, ["*"], "seat_1")
            append(EventType.NPC_SPEECH, {"text": data["reply"], "role_id": data["role_id"]}, ["*"])
        elif data["action"] == "search" and data.get("clue_id"):
            clue = script.clues[data["clue_id"]]
            append(EventType.CLUE_FOUND, {"clue_id": clue.clue_id, "location_id": clue.location_id},
                   ["*"] if clue.visibility == "public" else ["seat_1"])
        elif data["action"] == "vote":
            if data["role_id"] not in script.characters:
                raise ValueError("unknown accused role")
            append(EventType.VOTE, {"role_id": data["role_id"], "motive": data.get("motive", ""),
                                    "evidence_ids": data.get("evidence_ids", [])}, ["seat_1"], "seat_1")
        else:
            append(EventType.DM_NARRATION, {"text": data["reply"]}, ["*"])
        return data

    def phase_check(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        destinations = {
            "begin": Phase.READ, "read_done": Phase.ACT_OPEN,
            "enter_search": Phase.SEARCH, "leave_search": Phase.ACT_OPEN,
            "enter_confront": Phase.CONFRONT, "leave_confront": Phase.ACT_OPEN,
            "vote": Phase.VOTE, "recap": Phase.RECAP, "end": Phase.END,
        }
        target = destinations.get(data["action"])
        if target:
            transition(state.phase, target, last_act=True)
            store.append(GameEvent(seq=0, game_id=state.game_id, actor_seat_id="system",
                                   turn=state.turn, phase=state.phase, type=EventType.PHASE_CHANGE,
                                   payload={"to": target.value}, visible_to=["*"]))
            data["target_phase"] = target.value
        return data

    graph = StateGraph(TurnState)
    for name, func in (("ingest_turn", ingest_turn), ("router", router),
                       ("npc_dispatch", npc_dispatch), ("search_evidence", search_evidence),
                       ("dm_narrate", dm_narrate), ("leak_check", leak_check),
                       ("director_check", director_check), ("memory_write", memory_write),
                       ("phase_check", phase_check)):
        graph.add_node(name, func)
    graph.add_edge(START, "ingest_turn")
    graph.add_edge("ingest_turn", "router")
    graph.add_conditional_edges("router", lambda d: d["route"],
                                {"npc": "npc_dispatch", "search": "search_evidence", "dm": "dm_narrate"})
    graph.add_edge("npc_dispatch", "leak_check")
    graph.add_edge("leak_check", "director_check")
    graph.add_edge("search_evidence", "director_check")
    graph.add_edge("dm_narrate", "director_check")
    graph.add_edge("director_check", "memory_write")
    graph.add_edge("memory_write", "phase_check")
    graph.add_edge("phase_check", END)
    return graph.compile()
