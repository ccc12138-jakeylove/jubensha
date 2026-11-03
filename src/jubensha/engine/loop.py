from __future__ import annotations

from typing import TypedDict
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor

from langgraph.graph import END, START, StateGraph

from jubensha.agents.dm import narrate
from jubensha.agents.npc import respond
from jubensha.agents.fallback import safe_response_with_source
from jubensha.agents.director import decide
from jubensha.engine.fsm import Phase, transition
from jubensha.engine.claims import normalize_probe
from jubensha.engine.guard import blocked_input, check_npc_output, semantic_leak_check
from jubensha.engine.perception import build_perception
from jubensha.engine.search import available_clues, select_clue
from jubensha.schema.events import EventType, GameEvent
from jubensha.schema.claims import Claim
from jubensha.schema.ir import Script
from jubensha.storage.events import EventStore
from jubensha.storage.checkpoints import PgCheckpointer


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
    bundle_clue_ids: list[str]
    target_phase: str
    npc_question: str
    npc_is_lie: bool
    leak_blocked: bool
    input_blocked: bool
    npc_outputs: list[dict]
    director_message: str
    actor_seat_id: str


def build_turn_graph(script: Script, store: EventStore, observer=None):
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
        actor_seat_id = data.get("actor_seat_id") or next(iter(state.seats))
        if actor_seat_id not in state.seats:
            raise PermissionError("unknown seat")
        data["actor_seat_id"] = actor_seat_id
        valid = {
            "begin": {Phase.ENTRY}, "read_done": {Phase.READ},
            "enter_search": {Phase.ACT_OPEN}, "leave_search": {Phase.SEARCH},
            "search": {Phase.SEARCH}, "search_bundle": {Phase.SEARCH},
            "talk": {Phase.ACT_OPEN},
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
        phase_for_action = {
            "begin": Phase.READ,
            "read_done": Phase.ACT_OPEN, "talk": Phase.ACT_OPEN,
            "leave_search": Phase.ACT_OPEN,
            "enter_search": Phase.SEARCH, "search": Phase.SEARCH,
            "search_bundle": Phase.SEARCH,
            "leave_private": Phase.ACT_OPEN,
            "enter_private": Phase.PRIVATE, "private_talk": Phase.PRIVATE,
            "leave_confront": Phase.ACT_OPEN,
            "enter_confront": Phase.CONFRONT, "confront_talk": Phase.CONFRONT,
            "vote": Phase.VOTE,
        }.get(action)
        if phase_for_action is not None and phase_for_action not in act.allowed_phases:
            raise ValueError(f"本幕不允许 {phase_for_action.value} 阶段")
        if (action == "next_act" and act != ordered_acts[-1]
                and Phase.READ not in ordered_acts[ordered_acts.index(act) + 1].allowed_phases):
            raise ValueError("下一幕不允许 read 阶段")
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
        if action == "search_bundle" and script.search_mode != "location_bundle":
            raise ValueError("this script does not use location search bundles")
        if action == "search" and script.search_mode == "location_bundle":
            raise ValueError("this script searches by location")
        data["route"] = ("guard" if data["input_blocked"] and action in {"talk", "private_talk", "confront_talk"}
                         else "npc" if action in {"talk", "private_talk", "confront_talk"}
                         else "search" if action in {"search", "search_bundle"} else "dm")
        return data

    def guardrail_in(data: TurnState) -> TurnState:
        data["npc_question"] = data["text"]
        data["npc_is_lie"] = False
        data["reply"] = "你说的这些我听不懂。还是谈谈那晚发生的事吧。"
        data["npc_outputs"] = [{"role_id": data.get("role_id") or next(iter(script.characters)),
                                "reply": data["reply"], "is_lie": False,
                                "evidence_ids": [], "question": data["text"], "proactive": False}]
        return data

    def npc_dispatch(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        explicit_role = data.get("role_id")
        if explicit_role and explicit_role not in script.characters:
            raise ValueError("unknown role")
        if not explicit_role and data["action"] != "talk":
            raise ValueError("role is required outside public discussion")
        if explicit_role:
            roles = [explicit_role]
        else:
            topic_chars = set(data["text"])
            roles = sorted(script.characters,
                           key=lambda role_id: sum(char in script.characters[role_id].public_profile
                                                   for char in topic_chars), reverse=True)[:2]
        question = data["text"]
        if data["action"] == "confront_talk":
            owned = set(state.public_clue_ids) | set(state.seats[data["actor_seat_id"]].private_clue_ids)
            presented = data.get("evidence_ids", [])
            if any(clue_id not in owned for clue_id in presented):
                raise ValueError("只能出示已获得的线索")
            question += "\n出示的线索：" + "；".join(script.clues[clue_id].surface_text for clue_id in presented)
        data["npc_question"] = question
        history = store.events(data["game_id"])
        def answer(role_id: str) -> dict:
            perception = build_perception(script, state, role_id)
            response = respond(perception, question, history, store, state.game_id)
            return {"role_id": role_id, "reply": response.text,
                    "is_lie": response.is_lie, "evidence_ids": response.evidence_ids,
                    "question": question, "proactive": False}
        if len(roles) > 1:
            with ThreadPoolExecutor(max_workers=2) as executor:
                data["npc_outputs"] = list(executor.map(answer, roles))
        else:
            data["npc_outputs"] = [answer(roles[0])]
        data["reply"] = "\n".join(item["reply"] for item in data["npc_outputs"])
        data["npc_is_lie"] = any(item["is_lie"] for item in data["npc_outputs"])
        return data

    def search_evidence(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        if data["action"] == "search_bundle":
            clues = available_clues(script, state, data["location_id"], data["actor_seat_id"])
            if not clues:
                raise ValueError("此地点目前没有可搜查线索")
            data["bundle_clue_ids"] = [clue.clue_id for clue in clues]
            data["reply"] = "\n".join(clue.surface_text for clue in clues)
            return data
        clue = select_clue(script, state, data["location_id"], data["clue_id"],
                           data["actor_seat_id"])
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
            for output in data["npc_outputs"]:
                perception = build_perception(script, state, output["role_id"])
                def check_output():
                    if not check_npc_output(script, perception, output["reply"], output["question"]):
                        return "structure"
                    if not semantic_leak_check(script, output["reply"], store, state.game_id):
                        return "semantic"
                    return None
                reason = check_output()
                for _ in range(2):
                    if reason is None:
                        break
                    data["leak_blocked"] = True
                    store.guard_case(state.game_id, output["role_id"], output["question"],
                                     output["reply"], reason)
                    replacement = respond(
                        perception, output["question"], store.events(data["game_id"]),
                        store, state.game_id, retry=True)
                    output.update(reply=replacement.text, is_lie=replacement.is_lie,
                                  evidence_ids=replacement.evidence_ids)
                    reason = check_output()
                if reason is not None:
                    data["leak_blocked"] = True
                    store.guard_case(state.game_id, output["role_id"], output["question"],
                                     output["reply"], reason)
                    output["reply"], output["evidence_ids"] = safe_response_with_source(
                        perception, output["question"])
                    if not check_npc_output(script, perception, output["reply"], output["question"]):
                        output["reply"] = "这件事我没亲眼看见，不敢乱说。"
                        output["evidence_ids"] = []
                    output["is_lie"] = False
            data["reply"] = "\n".join(item["reply"] for item in data["npc_outputs"])
            data["npc_is_lie"] = any(item["is_lie"] for item in data["npc_outputs"])
        return data

    def director_check(data: TurnState) -> TurnState:
        if data["action"] != "talk" or data.get("input_blocked"):
            return data
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        history = store.events(data["game_id"])
        act = current_act(state)
        config = script.director_config
        decision = decide(state.phase, history,
                          {role_id: character.public_profile for role_id, character in script.characters.items()},
                          data["text"], {item["role_id"] for item in data.get("npc_outputs", [])},
                          {clue_id: script.clues[clue_id].surface_text for clue_id in state.public_clue_ids},
                          proactive_after=act.director_proactive_after or (config.proactive_after if config else 8),
                          hint_after=act.director_hint_after or (config.hint_after if config else 12),
                          critical_after=act.director_critical_after or (config.critical_after if config else 16),
                          max_proactive=config.max_proactive if config else 2)
        if decision.action == "hint" and decision.level >= 2:
            visited = {event.payload.get("location_id") for event in history
                       if event.type == EventType.CLUE_FOUND and "*" in event.visible_to}
            locations = [location.display_name for location in script.locations.values()
                         if location.location_id not in visited and location.searchable]
            if decision.level == 2 and locations:
                data["director_message"] = f"你们还可以检查{locations[0]}。"
            else:
                data["director_message"] = "已谈过的方向暂时没有新进展。可以继续搜证，或提交当前推理。"
        elif decision.action == "proactive" and decision.target:
            role_id = decision.target
            if role_id not in {item["role_id"] for item in data.get("npc_outputs", [])}:
                perception = build_perception(script, state, role_id)
                question = (f"玩家刚找到这条线索：{script.clues[decision.trigger_clue_id].surface_text}。你怎么看？"
                            if decision.trigger_clue_id else "你对刚才的话怎么看？")
                response = respond(perception, question, history, store, state.game_id)
                reply, is_lie = response.text, response.is_lie
                evidence_ids = response.evidence_ids
                if not check_npc_output(script, perception, reply, question) or not semantic_leak_check(script, reply, store, state.game_id):
                    store.guard_case(state.game_id, role_id, question, reply, "proactive")
                    reply, evidence_ids = safe_response_with_source(perception, question)
                    is_lie = False
                    if not check_npc_output(script, perception, reply, question):
                        reply = "这事我还想再看看。"
                        evidence_ids = []
                data.setdefault("npc_outputs", []).append(
                    {"role_id": role_id, "reply": reply, "is_lie": is_lie,
                     "evidence_ids": evidence_ids, "question": question, "proactive": True,
                     "trigger_clue_id": decision.trigger_clue_id})
        return data

    def memory_write(data: TurnState) -> TurnState:
        state = store.load(data["game_id"], script.acts[0].search_points_budget)
        turn = state.turn + 1
        seat_id = data["actor_seat_id"]
        def append(kind: EventType, payload: dict, visible: list[str], actor: str = "system"):
            store.append(GameEvent(seq=0, game_id=state.game_id, actor_seat_id=actor,
                                   turn=turn, phase=state.phase, type=kind, payload=payload,
                                   visible_to=visible))
        if data["action"] in {"talk", "private_talk", "confront_talk"}:
            private = data["action"] == "private_talk"
            visible = [seat_id, data["role_id"]] if private else ["*"]
            append(EventType.PLAYER_INPUT, {"text": data["text"], "role_id": data.get("role_id") or "",
                                            "private": private}, visible, seat_id)
            for output in data["npc_outputs"]:
                output_visible = [seat_id, output["role_id"]] if private else ["*"]
                append(EventType.NPC_SPEECH, {"text": output["reply"], "role_id": output["role_id"],
                                              "proactive": output["proactive"],
                                              "evidence_ids": output["evidence_ids"],
                                              "trigger_clue_id": output.get("trigger_clue_id")}, output_visible)
                claim = Claim(claim_id=uuid4().hex, role_id=output["role_id"], turn=turn,
                              proposition=output["reply"],
                              truth_value="false" if output["is_lie"] else "unknown",
                              is_lie=output["is_lie"], evidence_ids=output["evidence_ids"])
                append(EventType.CLAIM, claim.model_dump() | {"probe": normalize_probe(output["question"])}, output_visible)
            if data.get("director_message"):
                append(EventType.DM_NARRATION, {"text": data["director_message"], "director_level": 2}, ["*"])
        elif data["action"] in {"search", "search_bundle"}:
            clue_ids = data.get("bundle_clue_ids") or [data["clue_id"]]
            bundle_id = uuid4().hex if data["action"] == "search_bundle" else None
            for index, clue_id in enumerate(clue_ids):
                clue = script.clues[clue_id]
                payload = {"clue_id": clue.clue_id, "location_id": clue.location_id,
                           "search_cost": (1 if index == 0 else 0) if bundle_id else clue.search_cost,
                           "act_id": state.act_id}
                if bundle_id:
                    payload["bundle_id"] = bundle_id
                append(EventType.CLUE_FOUND, payload,
                       ["*"] if clue.visibility == "public" else [seat_id], seat_id)
        elif data["action"] == "vote":
            if data["role_id"] not in script.characters:
                raise ValueError("unknown accused role")
            owned = set(state.public_clue_ids) | set(state.seats[seat_id].private_clue_ids)
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
    def observed(name, func):
        if observer is None:
            return func
        def run(data):
            observer("node_start", name)
            result = func(data)
            observer("node_end", name)
            return result
        return run
    for name, func in (("ingest_turn", ingest_turn), ("router", router),
                       ("guardrail_in", guardrail_in),
                       ("npc_dispatch", npc_dispatch), ("search_evidence", search_evidence),
                       ("dm_narrate", dm_narrate), ("leak_check", leak_check),
                       ("director_check", director_check), ("memory_write", memory_write),
                       ("phase_check", phase_check)):
        graph.add_node(name, observed(name, func))
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
    return graph.compile(checkpointer=PgCheckpointer(store.path, schema=store.schema))


def run_turn(graph, store: EventStore, script: Script, data: TurnState):
    state = store.load(data["game_id"], script.acts[0].search_points_budget)
    return graph.invoke(data, {"configurable": {"thread_id": f"{state.game_id}:{state.turn + 1}"}})
