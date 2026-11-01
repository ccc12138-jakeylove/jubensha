from __future__ import annotations

from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from jubensha.agents.dm import narrate
from jubensha.agents.npc import respond
from jubensha.engine.fsm import Phase, transition
from jubensha.engine.claims import normalize_probe
from jubensha.engine.guard import blocked_input, check_npc_output, semantic_leak_check
from jubensha.engine.perception import build_perception
from jubensha.engine.search import select_clue
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.claims import Claim
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.checkpoints import SQLiteCheckpointer


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
    npc_question: str
    npc_is_lie: bool
    leak_blocked: bool
    input_blocked: bool


def build_turn_graph(script: Script, store: EventStore):
    ordered_acts = sorted(script.acts, key=lambda act: act.order)

    def current_act(state):
        return next(act for act in ordered_acts if act.act_id == state.act_id)

    def ingest_turn(data: TurnState) -> TurnState:
        data["text"] = data.get("text", "").strip()[:1000]
        data["input_blocked"] = blocked_input(data["text"])
        return data

    def router(data: TurnState) -> TurnState:
        action = data["action"]
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        valid = {
            "begin": {Phase.ENTRY}, "read_done": {Phase.READ},
            "enter_search": {Phase.ACT_OPEN}, "leave_search": {Phase.SEARCH},
            "search": {Phase.SEARCH}, "talk": {Phase.ACT_OPEN},
            "enter_private": {Phase.ACT_OPEN}, "private_talk": {Phase.PRIVATE},
            "leave_private": {Phase.PRIVATE},
            "enter_confront": {Phase.ACT_OPEN}, "leave_confront": {Phase.CONFRONT},
            "confront_talk": {Phase.CONFRONT},
            "vote": {Phase.CONFRONT}, "recap": {Phase.VOTE},
            "next_act": {Phase.VOTE}, "end": {Phase.RECAP},
        }
        if action not in valid or state.phase not in valid[action]:
            raise ValueError(f"action {action} is unavailable in {state.phase.value}")
        act = current_act(state)
        if action == "enter_private" and Phase.PRIVATE not in act.allowed_phases:
            raise ValueError("本幕不可私聊")
        if action == "enter_private" and state.private_chats_used >= act.private_chat_budget:
            raise ValueError("本幕私聊次数已用完")
        if action == "enter_private" and data.get("role_id") not in script.characters:
            raise ValueError("请选择私聊对象")
        if action == "private_talk" and data.get("role_id") != state.private_role_id:
            raise ValueError("当前私聊对象不匹配")
        if action == "recap" and act != ordered_acts[-1]:
            raise ValueError("尚有下一幕")
        if action == "next_act" and act == ordered_acts[-1]:
            raise ValueError("已经是最后一幕")
        data["route"] = ("guard" if data["input_blocked"] and action in {"talk", "private_talk", "confront_talk"}
                         else "npc" if action in {"talk", "private_talk", "confront_talk"}
                         else "search" if action == "search" else "dm")
        return data

    def guardrail_in(data: TurnState) -> TurnState:
        data["npc_question"] = data["text"]
        data["npc_is_lie"] = False
        data["reply"] = "你说的这些我听不懂。还是谈谈那晚发生的事吧。"
        return data

    def npc_dispatch(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        if data["role_id"] not in script.characters:
            raise ValueError("unknown role")
        question = data["text"]
        if data["action"] == "confront_talk":
            owned = set(state.public_clue_ids) | set(next(iter(state.seats.values())).private_clue_ids)
            presented = data.get("evidence_ids", [])
            if any(clue_id not in owned for clue_id in presented):
                raise ValueError("只能出示已获得的线索")
            question += "\n出示的线索：" + "；".join(script.clues[clue_id].surface_text for clue_id in presented)
        perception = build_perception(script, state, data["role_id"])
        data["npc_question"] = question
        data["reply"], data["npc_is_lie"] = respond(
            perception, question, store.events(data["game_id"]), store, state.game_id)
        return data

    def search_evidence(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        clue = select_clue(script, state, data["location_id"], data["clue_id"])
        data["reply"] = clue.surface_text
        return data

    def dm_narrate(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        phase_text = {
            "begin": "请阅读案件简报。", "read_done": "现在可以询问在场的人。",
            "enter_search": "请选择搜查地点。", "leave_search": "搜证结束，可以继续询问。",
            "enter_private": "请选择私聊对象。", "leave_private": "私聊结束。",
            "enter_confront": "请出示证据或提交指认。", "leave_confront": "继续询问吧。",
            "vote": "指认已记录。", "recap": "真相已揭晓。",
            "next_act": "下一幕开始。", "end": "本局结束。",
        }
        data["reply"] = narrate(script, state) if data["action"] == "begin" else phase_text[data["action"]]
        return data

    def leak_check(data: TurnState) -> TurnState:
        if data["route"] == "npc":
            state = store.load(data["game_id"], script.acts[0].search_points_budget)
            perception = build_perception(script, state, data["role_id"])
            def output_allowed():
                return (check_npc_output(script, perception, data["reply"])
                        and semantic_leak_check(script, data["reply"], store, state.game_id))
            allowed = output_allowed()
            for _ in range(2):
                if allowed:
                    break
                data["leak_blocked"] = True
                data["reply"], data["npc_is_lie"] = respond(
                    perception, data["npc_question"], store.events(data["game_id"]),
                    store, state.game_id, retry=True)
                allowed = output_allowed()
            if not allowed:
                data["reply"] = "这事我不清楚。"
                data["npc_is_lie"] = False
        return data

    def director_check(data: TurnState) -> TurnState:
        return data

    def memory_write(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        turn = state.turn + 1
        seat_id = next(iter(state.seats))
        def append(kind: EventType, payload: dict, visible: list[str], actor: str = "system"):
            store.append(GameEvent(seq=0, game_id=state.game_id, actor_seat_id=actor,
                                   turn=turn, phase=state.phase, type=kind, payload=payload,
                                   visible_to=visible))
        if data["action"] in {"talk", "private_talk", "confront_talk"}:
            private = data["action"] == "private_talk"
            visible = [seat_id, data["role_id"]] if private else ["*"]
            append(EventType.PLAYER_INPUT, {"text": data["text"], "role_id": data["role_id"],
                                            "private": private}, visible, seat_id)
            append(EventType.NPC_SPEECH, {"text": data["reply"], "role_id": data["role_id"]}, visible)
            claim = Claim(claim_id=uuid4().hex, role_id=data["role_id"], turn=turn,
                          proposition=data["reply"],
                          truth_value="false" if data.get("npc_is_lie") else "unknown",
                          is_lie=data.get("npc_is_lie", False), evidence_ids=[])
            append(EventType.CLAIM, claim.model_dump() | {"probe": normalize_probe(data["npc_question"])}, visible)
        elif data["action"] == "search" and data.get("clue_id"):
            clue = script.clues[data["clue_id"]]
            append(EventType.CLUE_FOUND, {"clue_id": clue.clue_id, "location_id": clue.location_id,
                                          "search_cost": clue.search_cost, "act_id": state.act_id},
                   ["*"] if clue.visibility == "public" else [seat_id])
        elif data["action"] == "vote":
            if data["role_id"] not in script.characters:
                raise ValueError("unknown accused role")
            owned = set(state.public_clue_ids) | set(next(iter(state.seats.values())).private_clue_ids)
            if any(clue_id not in owned for clue_id in data.get("evidence_ids", [])):
                raise ValueError("只能引用已获得的线索")
            append(EventType.VOTE, {"role_id": data["role_id"], "motive": data.get("motive", ""),
                                    "evidence_ids": data.get("evidence_ids", [])}, [seat_id], seat_id)
        else:
            append(EventType.DM_NARRATION, {"text": data["reply"]}, ["*"])
        return data

    def phase_check(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        destinations = {
            "begin": Phase.READ, "read_done": Phase.ACT_OPEN,
            "enter_search": Phase.SEARCH, "leave_search": Phase.ACT_OPEN,
            "enter_private": Phase.PRIVATE, "leave_private": Phase.ACT_OPEN,
            "enter_confront": Phase.CONFRONT, "leave_confront": Phase.ACT_OPEN,
            "vote": Phase.VOTE, "recap": Phase.RECAP,
            "next_act": Phase.READ, "end": Phase.END,
        }
        target = destinations.get(data["action"])
        if target:
            transition(state.phase, target, last_act=current_act(state) == ordered_acts[-1])
            payload = {"to": target.value}
            if data["action"] == "next_act":
                next_act = ordered_acts[ordered_acts.index(current_act(state)) + 1]
                payload.update(act_id=next_act.act_id,
                               search_points_budget=next_act.search_points_budget)
            if data["action"] == "enter_private":
                payload["role_id"] = data["role_id"]
            store.append(GameEvent(seq=0, game_id=state.game_id, actor_seat_id="system",
                                   turn=state.turn, phase=state.phase, type=EventType.PHASE_CHANGE,
                                   payload=payload, visible_to=["*"]))
            data["target_phase"] = target.value
        return data

    graph = StateGraph(TurnState)
    for name, func in (("ingest_turn", ingest_turn), ("router", router),
                       ("guardrail_in", guardrail_in),
                       ("npc_dispatch", npc_dispatch), ("search_evidence", search_evidence),
                       ("dm_narrate", dm_narrate), ("leak_check", leak_check),
                       ("director_check", director_check), ("memory_write", memory_write),
                       ("phase_check", phase_check)):
        graph.add_node(name, func)
    graph.add_edge(START, "ingest_turn")
    graph.add_edge("ingest_turn", "router")
    graph.add_conditional_edges("router", lambda d: d["route"],
                                {"npc": "npc_dispatch", "guard": "guardrail_in",
                                 "search": "search_evidence", "dm": "dm_narrate"})
    graph.add_edge("guardrail_in", "director_check")
    graph.add_edge("npc_dispatch", "leak_check")
    graph.add_edge("leak_check", "director_check")
    graph.add_edge("search_evidence", "director_check")
    graph.add_edge("dm_narrate", "director_check")
    graph.add_edge("director_check", "memory_write")
    graph.add_edge("memory_write", "phase_check")
    graph.add_edge("phase_check", END)
    return graph.compile(checkpointer=SQLiteCheckpointer(store.path))


def run_turn(graph, store: EventStore, script: Script, data: TurnState):
    state = store.load(data["game_id"], script.acts[0].search_points_budget)
    return graph.invoke(data, {"configurable": {"thread_id": f"{state.game_id}:{state.turn + 1}"}})
