from jubensha.schema.ir import LintIssue, LinterReport, Script, SolvabilityResult


def lint_script(script: Script) -> LinterReport:
    blockers: list[LintIssue] = []
    warnings: list[LintIssue] = []

    def issue(code: str, severity: str, target_id: str, message: str, suggestion: str | None = None):
        item = LintIssue(code=code, severity=severity, target_id=target_id,
                         message=message, suggestion=suggestion)
        (blockers if severity == "blocker" else warnings).append(item)

    acts = {act.act_id for act in script.acts}
    event_ids = {event.event_id for event in script.truth_events}
    if not script.acts or len(acts) != len(script.acts) or len({act.order for act in script.acts}) != len(script.acts):
        issue("INVALID_ACT_ORDER", "blocker", script.script_id, "幕缺失或幕编号/顺序重复")
    for act in script.acts:
        if not {"read", "act_open", "vote"}.issubset({phase.value for phase in act.allowed_phases}):
            issue("ACT_MISSING_REQUIRED_PHASE", "blocker", act.act_id,
                  "幕缺少阅读、公聊或投票阶段")
        thresholds = (act.director_proactive_after, act.director_hint_after,
                      act.director_critical_after)
        if all(value is not None for value in thresholds) and not thresholds[0] < thresholds[1] < thresholds[2]:
            issue("INVALID_DIRECTOR_THRESHOLDS", "blocker", act.act_id,
                  "导演阈值应按主动发言、提示、关键提示递增")
    if not script.characters or script.seat_range[0] < 1 or script.seat_range[0] > script.seat_range[1]:
        issue("INVALID_CAST", "blocker", script.script_id, "角色或席位范围无效")
    for key, character in script.characters.items():
        if character.role_id != key or key not in script.knowledge:
            issue("BROKEN_CHARACTER_REFERENCE", "blocker", key, "角色键与 role_id 不符，或缺少认知切片")
        for secret_id in character.secret_ids:
            if secret_id not in script.secrets or script.secrets[secret_id].owner_role_id != key:
                issue("BROKEN_SECRET_OWNER", "blocker", key, f"秘密 {secret_id} 归属不一致")
    for key, knowledge in script.knowledge.items():
        if key not in script.characters or knowledge.role_id != key:
            issue("BROKEN_KNOWLEDGE_REFERENCE", "blocker", key, "认知切片与角色不匹配")
        for event_id in knowledge.knows_event_ids:
            if event_id not in event_ids:
                issue("BROKEN_KNOWLEDGE_REFERENCE", "blocker", key, f"未知事件 {event_id}")
        for clue_id in knowledge.knows_clue_ids:
            if clue_id not in script.clues:
                issue("BROKEN_KNOWLEDGE_REFERENCE", "blocker", key, f"未知线索 {clue_id}")
        for belief in knowledge.false_beliefs:
            if belief.source_event_id not in event_ids or any(
                clue_id not in script.clues for clue_id in belief.refuted_by_clue_ids):
                issue("BROKEN_BELIEF_REFERENCE", "blocker", key, "误信来源或反证线索不存在")
    for key, secret in script.secrets.items():
        if key != secret.secret_id or secret.owner_role_id not in script.characters:
            issue("BROKEN_SECRET_OWNER", "blocker", key, "秘密 ID 或归属角色无效")
        for clue_id in secret.exposed_by_clue_ids:
            if clue_id not in script.clues:
                issue("BROKEN_SECRET_REFERENCE", "blocker", key, f"暴露线索 {clue_id} 不存在")
    if set(script.leak_surfaces) != set(script.secrets):
        issue("BROKEN_LEAK_SURFACE", "blocker", script.script_id, "泄密表与秘密 ID 不一致")
    for key, surface in script.leak_surfaces.items():
        if surface.secret_id != key:
            issue("BROKEN_LEAK_SURFACE", "blocker", key, "泄密表 secret_id 不匹配")
    for key, location in script.locations.items():
        if key != location.location_id or location.capacity_per_act < 0:
            issue("BROKEN_LOCATION_REFERENCE", "blocker", key, "地点 ID 或容量无效")
        for neighbor in location.connected_to:
            if neighbor not in script.locations:
                issue("BROKEN_LOCATION_REFERENCE", "blocker", key, f"相邻地点 {neighbor} 不存在")
    for relationship in script.relationships:
        if relationship.from_role not in script.characters and relationship.to_role not in script.characters:
            issue("BROKEN_RELATIONSHIP", "blocker", relationship.from_role,
                  "关系两端均不是可对话角色")
        for clue_id in relationship.evidence_clue_ids:
            if clue_id not in script.clues:
                issue("BROKEN_RELATIONSHIP", "blocker", relationship.from_role,
                      f"关系证据 {clue_id} 不存在")
    for event in script.truth_events:
        if event.act_id not in acts or event.location_id not in script.locations:
            issue("BROKEN_EVENT_REFERENCE", "blocker", event.event_id, "事件引用了不存在的幕或地点")
        if event.t_end is not None and event.t_end < event.t_start:
            issue("INVALID_TIME_RANGE", "blocker", event.event_id, "事件结束时间早于开始时间")
        if abs(event.t_start) > 10080 or (event.t_end is not None and abs(event.t_end) > 10080):
            issue("UNUSUAL_TIME_OFFSET", "high", event.event_id,
                  "相对分钟数超过一周，需核对是否把原文字符位置误解析为时间")
        for clue_id in event.evidence_clue_ids:
            if clue_id not in script.clues:
                issue("BROKEN_CLUE_REFERENCE", "blocker", event.event_id, f"缺少线索 {clue_id}")
    for index, first in enumerate(script.truth_events):
        for second in script.truth_events[index + 1:]:
            if first.act_id != second.act_id or first.location_id == second.location_id:
                continue
            if not set(first.actor_ids).intersection(second.actor_ids):
                continue
            if first.t_start < (second.t_end if second.t_end is not None else second.t_start + 1) and second.t_start < (first.t_end if first.t_end is not None else first.t_start + 1):
                issue("TIMELINE_CONFLICT", "blocker", f"{first.event_id}/{second.event_id}",
                      "同一角色在重叠时间位于两个地点")

    reachable: set[str] = set()
    pending = dict(script.clues)
    changed = True
    while changed:
        changed = False
        for clue_id, clue in list(pending.items()):
            location = script.locations.get(clue.location_id)
            if (location and location.searchable
                    and set(clue.act_available).intersection(acts).intersection(location.act_availability)
                    and set(clue.prerequisites).issubset(reachable)):
                reachable.add(clue_id)
                del pending[clue_id]
                changed = True
    for clue_id, clue in script.clues.items():
        if clue.clue_id != clue_id or clue.search_cost < 1:
            issue("INVALID_CLUE", "blocker", clue_id, "线索 ID 或搜证成本无效")
        if clue.location_id not in script.locations:
            issue("BROKEN_LOCATION_REFERENCE", "blocker", clue_id, "线索地点不存在")
        if not clue.reveals_event_ids and not clue.reveals_secret_ids:
            issue("ORPHAN_CLUE", "high", clue_id, "线索未指向事件或秘密")
        for event_id in clue.reveals_event_ids:
            if event_id not in event_ids:
                issue("BROKEN_EVENT_REFERENCE", "blocker", clue_id, f"缺少事件 {event_id}")
        for secret_id in clue.reveals_secret_ids:
            if secret_id not in script.secrets:
                issue("BROKEN_SECRET_REFERENCE", "blocker", clue_id, f"缺少秘密 {secret_id}")
    for clue_id in pending:
        issue("UNREACHABLE_CLUE", "blocker", clue_id, "地点、幕或前置条件使线索不可达",
              "检查地点开放幕和线索前置条件")
    for secret in script.secrets.values():
        if not secret.exposed_by_clue_ids:
            issue("UNEXPOSED_SECRET", "medium", secret.secret_id, "秘密没有直接暴露线索")

    culprits = {role_id for role_id, character in script.characters.items() if character.is_culprit}
    if len(culprits) > 1 and script.win_condition.type in ("accuse", "vote"):
        issue("MULTIPLE_CULPRITS", "blocker", script.script_id,
              "单凶指认规则下有多个真凶，存在多解",
              "明确唯一真凶，或改用支持多目标的胜利条件")
    culprit_events = {event.event_id for event in script.truth_events
                      if culprits.intersection(event.actor_ids)}
    evidence = [clue_id for clue_id in reachable
                if culprit_events.intersection(script.clues[clue_id].reveals_event_ids)
                or any(script.secrets[secret_id].owner_role_id in culprits
                       for secret_id in script.clues[clue_id].reveals_secret_ids
                       if secret_id in script.secrets)]
    relevant_clues = set(evidence)
    for clue_id in list(relevant_clues):
        relevant_clues.update(key for key in script.clues[clue_id].prerequisites
                              if key in script.clues)
    chain_cost = sum(script.clues[key].search_cost for key in relevant_clues)
    total_budget = sum(act.search_points_budget for act in script.acts)
    if chain_cost > total_budget:
        issue("KEY_CHAIN_RESOURCE_RISK", "medium", script.script_id,
              f"完整相关证据链需 {chain_cost} 点，剧本总预算仅 {total_budget} 点；请人工确认可用子路径是否足够",
              "增加预算、减少必需线索成本，或确认较短推理路径")
    solvable = bool(culprits and evidence)
    if not solvable:
        issue("MISSING_KEY_EVIDENCE", "blocker", script.script_id,
              "无法从可达线索指向真凶", "补充能证明真凶相关事件的可达线索")
    def prerequisite_path(clue_id: str, seen: set[str] | None = None) -> list[str]:
        seen = seen or set()
        if clue_id in seen:
            return []
        seen.add(clue_id)
        path = []
        for prerequisite in script.clues[clue_id].prerequisites:
            if prerequisite in script.clues:
                path.extend(prerequisite_path(prerequisite, seen))
        path.append(clue_id)
        return path

    candidate_paths = [prerequisite_path(clue_id) for clue_id in evidence]
    best_path = min(candidate_paths, key=lambda path: sum(script.clues[key].search_cost for key in path)) if candidate_paths else []
    minimum_cost = sum(script.clues[key].search_cost for key in best_path) if best_path else None
    if minimum_cost is not None and minimum_cost > total_budget:
        issue("BUDGET_UNSOLVABLE", "blocker", script.script_id,
              f"最短关键线索路径需 {minimum_cost} 点，预算仅 {total_budget} 点",
              "增加搜证预算或降低关键线索成本")
    red_herring_ratio = (sum(clue.red_herring for clue in script.clues.values()) / len(script.clues)
                         if script.clues else 0.0)
    if red_herring_ratio > 0.5:
        issue("EXCESS_RED_HERRINGS", "medium", script.script_id,
              "超过半数线索为红鲱鱼，可能淹没关键证据")
    difficulty = min(5, max(1, 1 + len(script.clues) // 6 + len(script.acts) - 1
                            + int(red_herring_ratio > 0.25)
                            + int(any(clue.prerequisites for clue in script.clues.values()))))
    return LinterReport(
        passed=not blockers, blockers=blockers, warnings=warnings,
        solvability=SolvabilityResult(solvable=solvable,
                                      optimal_path_clue_ids=best_path,
                                      missing_evidence=[] if solvable else ["culprit_evidence"],
                                      requires_human_review=True,
                                      minimum_cost=minimum_cost, search_budget=total_budget,
                                      alternative_culprits=sorted(culprits) if len(culprits) > 1 else []),
        difficulty=difficulty, red_herring_ratio=red_herring_ratio,
    )
