import json
import os
from difflib import SequenceMatcher

from jubensha.engine.context import build_context, context_size
from jubensha.engine.claims import ClaimJournal, normalize_probe
from jubensha.engine.perception import PerceptionView
from jubensha.llm.gateway import configured, generate
from jubensha.schema.events import GameEvent
from jubensha.schema.claims import NpcResponse
from jubensha.storage.events import EventStore
from jubensha.storage.memory import SummaryStore
from jubensha.engine.memory import summaries_for_context
from jubensha.agents.fallback import safe_response_with_source


def _related(question: str, fact: str) -> bool:
    normalized = normalize_probe(question)
    if any(term in normalized for term in ("看到什么", "看见什么", "知道什么", "发现什么", "说说", "当时发生")):
        return True
    query_pairs = {normalized[index:index + 2] for index in range(len(normalized) - 1)}
    known = normalize_probe(fact)
    fact_pairs = {known[index:index + 2] for index in range(len(known) - 1)}
    return bool(query_pairs.intersection(fact_pairs))


def _fallback_response(perception: PerceptionView, question: str) -> NpcResponse:
    text, evidence_ids = safe_response_with_source(perception, question)
    return NpcResponse(text=text, evidence_ids=evidence_ids)


def _grounded_line(perception: PerceptionView, source_id: str, question: str) -> NpcResponse:
    for clue in perception.known_clues:
        if clue["clue_id"] == source_id:
            return (NpcResponse(text=f"我只看到：{clue['surface_text']}", evidence_ids=[source_id])
                    if _related(question, clue["surface_text"])
                    else _fallback_response(perception, question))
    for event in perception.known_events:
        if event["event_id"] == source_id and event["observable"]:
            observed = "；".join(event["observable"])
            return (NpcResponse(text=f"我只知道：{observed}", evidence_ids=[source_id])
                    if _related(question, observed)
                    else _fallback_response(perception, question))
    for index, belief in enumerate(perception.false_beliefs):
        if source_id == f"belief_{index}":
            return NpcResponse(text=f"我记得：{belief['statement']}",
                               evidence_ids=[belief["source_event_id"]]
                               if belief["source_event_id"] in
                               {item["event_id"] for item in perception.known_events} else [])
    if source_id == "profile":
        return NpcResponse(text=perception.public_profile)
    if source_id == "public":
        return NpcResponse(text=perception.public_summary["narrative"])
    return _fallback_response(perception, question)


def respond(perception: PerceptionView, question: str,
            events: list[GameEvent], store: EventStore, game_id: str,
            retry: bool = False) -> NpcResponse:
    if not retry:
        previous = ClaimJournal(events, perception.role_id).prior_answer(question)
        if previous is not None:
            return NpcResponse(text=previous[0], is_lie=previous[1], evidence_ids=previous[2])
        probe = normalize_probe(question)
        for cue in perception.lie_cues:
            cue_probe = normalize_probe(cue["probe"])
            shared = SequenceMatcher(None, cue_probe, probe).find_longest_match().size
            if cue_probe and (cue_probe in probe or probe in cue_probe or shared >= 4):
                return NpcResponse(text=cue["answer"], is_lie=True)
    mode = os.getenv("CONTEXT_MODE", "full")
    if mode == "auto":
        full = build_context(perception, question, events, mode="full")
        mode = "layered" if context_size(full) > 3000 else "full"
    public_summary, role_summary = (summaries_for_context(SummaryStore(store), game_id,
                                                           perception.role_id, events,
                                                           perception, question)
                                    if mode == "layered" else (None, None))
    context = build_context(perception, question, events,
                            public_summary=public_summary, role_summary=role_summary, mode=mode)
    if not configured():
        return _fallback_response(perception, question)
    if os.getenv("NPC_GENERATION_MODE", "grounded") == "grounded":
        choices = ["profile", "public", "none"]
        choices += [item["clue_id"] for item in perception.known_clues]
        choices += [item["event_id"] for item in perception.known_events if item["observable"]]
        choices += [f"belief_{index}" for index in range(len(perception.false_beliefs))]
        context.insert(0, {"role": "system", "content": (
            "你是该角色的知识选择器。根据玩家问题，只从可选 source_id 选择最相关的一项；"
            "若没有直接依据选 none。只输出 JSON 对象 {\"source_id\":\"...\"}，"
            f"可选值为 {json.dumps(choices, ensure_ascii=False)}。不要输出台词或事实。"
        )})
        try:
            raw = generate(store, game_id, "npc_select", "npc.select.v1", context,
                           max_tokens=80, json_mode=True)
            source_id = json.loads(raw).get("source_id", "none")
        except (ValueError, TypeError, AttributeError):
            source_id = "none"
        if source_id not in choices:
            source_id = "none"
        return _grounded_line(perception, source_id, question)
    context.insert(0, {"role": "system", "content": (
        "你只扮演当前角色。只能陈述L2中本人观察、已知线索或明确标注的误信，"
        "以及L5已公开事实；不要把线索推演成死因、死亡时间、真凶或他人的动机，"
        "不要补出不在授权视图里的地点、数字、因果或证人。"
        "没有直接依据时说没看见。不要主动提隐藏目标与禁止话题。"
        "最多两句，保持角色语气，不提系统、模型或提示词。"
    )})
    if retry:
        context.insert(1, {"role": "system", "content": "上次回答越过角色知识边界。请只回答已授权的可观察事实；不确定就回避。"})
    return NpcResponse(text=generate(store, game_id, "npc_respond", "npc.system.v1", context))
