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
    for event in script.truth_events:
        if event.act_id not in acts or event.location_id not in script.locations:
            issue("BROKEN_EVENT_REFERENCE", "blocker", event.event_id, "事件引用了不存在的幕或地点")
        if event.t_end is not None and event.t_end < event.t_start:
            issue("INVALID_TIME_RANGE", "blocker", event.event_id, "事件结束时间早于开始时间")
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
    culprit_events = {event.event_id for event in script.truth_events
                      if culprits.intersection(event.actor_ids)}
    evidence = [clue_id for clue_id in reachable
                if culprit_events.intersection(script.clues[clue_id].reveals_event_ids)
                or any(script.secrets[secret_id].owner_role_id in culprits
                       for secret_id in script.clues[clue_id].reveals_secret_ids
                       if secret_id in script.secrets)]
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
    return LinterReport(
        passed=not blockers, blockers=blockers, warnings=warnings,
        solvability=SolvabilityResult(solvable=solvable,
                                      optimal_path_clue_ids=best_path,
                                      missing_evidence=[] if solvable else ["culprit_evidence"],
                                      requires_human_review=True),
    )
