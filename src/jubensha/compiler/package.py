import json
import re
from hashlib import sha256
from pathlib import Path

from jubensha.compiler.content import content_tags, pii_hits, suggested_rating
from jubensha.compiler.ingest import DocumentSegment, read_document
from jubensha.compiler.lint import lint_script
from jubensha.compiler.pipeline import CompilationDraft, ReviewItem
from jubensha.schema.ir import Script


def _source_files(folder: Path) -> tuple[Path, Path, Path]:
    inner = folder / folder.name.removeprefix("MIRAGE_")
    role_file = inner / "人物剧本.json"
    clue_file = inner / "线索.json"
    truth_file = folder / "_真相_GM专用.txt"
    for path in (role_file, clue_file, truth_file):
        if not path.is_file():
            raise FileNotFoundError(path)
    return role_file, clue_file, truth_file


_ACT_KEY = re.compile(r"^第?([一二三四五六七八九十\d]+)幕(?:线索)?$")
_CN_NUMBERS = {name: index for index, name in enumerate(
    ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十"), 1)}


def _role_acts(raw: dict) -> tuple[list[str], dict[str, list[dict]]]:
    if raw and all(re.fullmatch(r"第[一二三四五六七八九十\d]+幕", key) for key in raw):
        act_names = list(raw)
        names = list(dict.fromkeys(name for act in raw.values() for name in act))
        return act_names, {name: [raw[act].get(name, {}) for act in act_names] for name in names}
    return ["第一幕"], {name: [value] for name, value in raw.items()}


def _act_id_for_group(key: str, act_names: list[str], act_ids: list[str]) -> str | None:
    """识别线索表中的“第一幕/第二幕线索”分组；普通地点名返回 None。"""
    normalized = key.strip()
    for index, name in enumerate(act_names):
        if normalized in (name, f"{name}线索"):
            return act_ids[index]
    match = _ACT_KEY.fullmatch(normalized)
    if not match:
        return None
    token = match.group(1)
    index = int(token) if token.isdigit() else _CN_NUMBERS.get(token)
    if index is None or not 1 <= index <= len(act_ids):
        return None
    return act_ids[index - 1]


def _clue_entries(group: object) -> list[tuple[str | None, object, str]]:
    if isinstance(group, dict):
        return [(str(key), value, "private") for key, value in group.items()]
    if isinstance(group, list):
        return [(None, value, "public") for value in group]
    raise ValueError("clue group must be a list or object")


def compile_package(folder: Path, *, genre: str = "本格") -> CompilationDraft:
    role_file, clue_file, truth_file = _source_files(folder)
    roles_raw = json.loads(role_file.read_text(encoding="utf-8-sig"))
    clues_raw = json.loads(clue_file.read_text(encoding="utf-8-sig"))
    if not isinstance(roles_raw, dict) or not isinstance(clues_raw, dict):
        raise ValueError("rolebook and clue files must be JSON objects")
    act_names, roles = _role_acts(roles_raw)
    if not roles or not clues_raw:
        raise ValueError("package needs rolebooks and clues")
    readable_files = sorted(path for path in folder.glob("*.txt") if path != truth_file)
    files = [truth_file, role_file, clue_file, *readable_files]
    source_parts = []
    offsets = {}
    offset = 0
    for path in files:
        part = f"# {path.name}\n" + read_document(path.name.replace(".json", ".txt"), path.read_bytes()) + "\n"
        offsets[path] = (offset, offset + len(part))
        source_parts.append(part)
        offset += len(part)
    source_text = "".join(source_parts)
    title = folder.name.removeprefix("MIRAGE_")
    script_id = "package_" + sha256(title.encode("utf-8")).hexdigest()[:12]
    act_ids = [f"A{index:02d}" for index in range(1, len(act_names) + 1)]
    role_ids = {name: f"R{index:02d}" for index, name in enumerate(roles, 1)}
    characters = {}
    knowledge = {}
    provenance = {}
    for name, parts in roles.items():
        role_id = role_ids[name]
        first = parts[0] if isinstance(parts[0], dict) else {}
        goals_by_act = {}
        for act_id, part in zip(act_ids, parts):
            if (isinstance(part, dict) and isinstance(part.get("Purpose"), str)
                    and part["Purpose"].strip()):
                goals_by_act.setdefault(act_id, []).append(part["Purpose"].strip())
        # private_goals 只保留第一幕目标：后续幕目标只通过 private_goals_by_act
        # 在对应幕次进入角色视角，避免开局就把后续剧情交给 NPC。
        characters[role_id] = {
            "role_id": role_id, "display_name": name, "is_culprit": False,
            "public_profile": f"{name}。",
            "private_goals": goals_by_act.get(act_ids[0], []),
            "private_goals_by_act": goals_by_act,
            "persona_style": str(first.get("Performance") or "保持角色语气")[:400],
            "secret_ids": [],
            "speech_constraints": [str(first["Ability"])[:400]] if first.get("Ability") else [],
        }
        statements = []
        start, end = offsets[role_file]
        for part_index, part in enumerate(parts):
            if not isinstance(part, dict):
                continue
            for field in ("Story", "Script"):
                for sentence in re.split(r"(?<=[。！？.!?])\s*", str(part.get(field, ""))):
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    anchor = json.dumps(sentence[:40], ensure_ascii=False)[1:-1]
                    found = source_text.find(anchor, start, end)
                    statements.append({"statement_id": f"K{role_id}_{len(statements) + 1:02d}",
                                       "text": sentence, "approved": False,
                                       "act_id": act_ids[part_index],
                                       "source_doc": str(role_file) if found >= 0 else None,
                                       "source_span": [found, found + len(anchor)] if found >= 0 else None})
        knowledge[role_id] = {"role_id": role_id, "knows_event_ids": [],
                              "knows_clue_ids": [], "false_beliefs": [],
                              "forbidden_topics": [], "statements": statements}
        found = source_text.find(json.dumps(name, ensure_ascii=False), start, end)
        if found >= 0:
            provenance[f"characters.{role_id}"] = {
                "field_path": f"characters.{role_id}", "source_doc": str(role_file),
                "source_span": [found, found + len(name) + 2], "confidence": 1.0,
            }
    locations = {}
    clues = {}
    grouped_by_act = (len(act_ids) > 1
                      and any(_act_id_for_group(key, act_names, act_ids) for key in clues_raw))
    clue_groups: list[tuple[str, str, list[tuple[str | None, object, str]]]] = []
    for group_key, group_value in clues_raw.items():
        act_id = (_act_id_for_group(group_key, act_names, act_ids)
                  if grouped_by_act else None)
        if act_id is None:
            # 多幕本没有幕分组时保守归入第一幕；作者必须在校对配置中逐幕确认。
            clue_groups.append((act_ids[0], group_key, _clue_entries(group_value)))
            continue
        if not isinstance(group_value, dict):
            raise ValueError(f"act clue group {group_key} must be an object of locations")
        clue_groups.extend((act_id, location_name, _clue_entries(items))
                           for location_name, items in group_value.items())
    location_ids: dict[str, str] = {}
    location_acts: dict[str, list[str]] = {}
    location_counts: dict[str, dict[str, int]] = {}
    for act_id, location_name, entries in clue_groups:
        if location_name not in location_ids:
            location_ids[location_name] = f"L{len(location_ids) + 1:02d}"
        if act_id not in location_acts.setdefault(location_name, []):
            location_acts[location_name].append(act_id)
        location_counts.setdefault(location_name, {})[act_id] = (
            location_counts.setdefault(location_name, {}).get(act_id, 0) + len(entries))
    act_order = {act_id: index for index, act_id in enumerate(act_ids)}
    for location_name, location_id in location_ids.items():
        acts_for_location = sorted(location_acts[location_name], key=act_order.get)
        locations[location_id] = {
            "location_id": location_id, "display_name": location_name,
            "description": location_name, "searchable": True,
            "capacity_per_act": max(1, max(location_counts[location_name].values())),
            "act_availability": acts_for_location, "connected_to": []}
    target_indexes: dict[str, int] = {}
    for act_id, location_name, entries in clue_groups:
        location_id = location_ids[location_name]
        for clue_name, item, visibility in entries:
            target_indexes[location_name] = target_indexes.get(location_name, 0) + 1
            target_index = target_indexes[location_name]
            surface = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            clue_id = f"C{len(clues) + 1:03d}"
            clues[clue_id] = {"clue_id": clue_id,
                              "display_name": clue_name or surface.splitlines()[0][:24] or clue_id,
                              "search_label": f"待搜查目标 {target_index}",
                              "surface_text": surface, "truth_value": "true",
                              "location_id": location_id, "act_available": [act_id],
                              "search_cost": 1, "prerequisites": [],
                              "reveals_event_ids": [], "reveals_secret_ids": [],
                              "visibility": visibility, "red_herring": False}
            start, end = offsets[clue_file]
            anchor = json.dumps(surface[:40], ensure_ascii=False)[1:-1]
            found = source_text.find(anchor, start, end)
            if found >= 0:
                provenance[f"clues.{clue_id}"] = {
                    "field_path": f"clues.{clue_id}", "source_doc": str(clue_file),
                    "source_span": [found, found + len(anchor)], "confidence": 1.0,
                }
    acts = [{"act_id": act_id, "order": index, "title": name,
             "public_narrative": "案件开始，请阅读角色本并展开调查。",
             "allowed_phases": ["read", "act_open", "search", "private", "confront", "vote"],
             "search_points_budget": 5}
            for index, (act_id, name) in enumerate(zip(act_ids, act_names), 1)]
    tags = content_tags(source_text)
    reconcile_warnings = ["真相事件和线索关联需由作者校对"]
    if len(act_ids) > 1 and not grouped_by_act:
        reconcile_warnings.append(
            "线索表未按幕分组，已保守归入第一幕；请逐幕核对 act_available")
    ir = {"script_id": script_id, "title": title, "genre": genre, "ir_version": "1.1",
          "tone": "悬疑", "seat_range": [1, len(roles)], "search_mode": "location_bundle",
          "win_condition": {"type": "accuse", "required": ["culprit", "motive", "key_evidence"],
                            "partial_credit": True},
          "acts": acts, "characters": characters, "truth_events": [], "clues": clues,
          "locations": locations, "secrets": {}, "knowledge": knowledge,
          "relationships": [], "leak_surfaces": {}, "provenance": provenance,
          "tags": tags, "content_rating": suggested_rating(tags),
          "act_scope_reviewed": False,
          "parser_meta": {"source_files": [str(path) for path in files],
                          "segments": [], "field_confidence": {},
                          "reconcile_warnings": reconcile_warnings}}
    script = Script.model_validate(ir)
    report = lint_script(script)
    ir["linter_report"] = report.model_dump()
    ir["difficulty"] = report.difficulty
    reviews = [ReviewItem(field_path=field, confidence=0,
                          conflict_type="low_confidence", message=message)
               for field, message in (
                   ("genre", "请核对剧本类型"),
                   ("win_condition", "请核对该剧本的胜利条件"),
                   ("acts", "请核对每幕公开叙述与搜证预算"),
                   ("characters", "公开角色简介尚未从私密角色本校对"),
                   ("truth_events", "请依据 GM 真相建立客观时间线和真凶"),
                   ("clues", "请核对线索公开性、真伪、费用及事件/秘密关联"),
                   ("knowledge", "请核对每名角色知道的事件、线索与误信"),
                   ("relationships", "请核对角色关系与证据来源"),
               )]
    if len(act_ids) > 1:
        reviews.append(ReviewItem(
            field_path="act_scope", confidence=0,
            conflict_type="low_confidence",
            message="多幕本必须逐幕核对线索/地点开放范围与角色分幕目标"))
    if ir["content_rating"] == "18+":
        reviews.append(ReviewItem(field_path="content_rating", confidence=0.5,
                                  conflict_type="content_rating", message="高风险内容分级需人工复核"))
    reviews.extend(ReviewItem(field_path=issue.target_id, confidence=0,
                              conflict_type="script_bug", message=issue.message)
                   for issue in report.blockers)
    reviews.extend(ReviewItem(field_path="source_text", confidence=1,
                              conflict_type="pii", message=f"原文疑似包含 {kind}，需核对虚构声明")
                   for kind in pii_hits(source_text))
    segments = [DocumentSegment(source_doc=str(path), title=path.name, kind="source",
                                text="", source_span=offsets[path]) for path in files]
    return CompilationDraft(filename=folder.name, source_text=source_text,
                            segments=segments, ir=ir, review_items=reviews, valid=report.passed)


def apply_review(ir: dict, review: dict, source_text: str = "") -> dict:
    if review["script_id"] != ir["script_id"]:
        raise ValueError("review script_id differs from draft")
    updated = json.loads(json.dumps(ir, ensure_ascii=False))
    for field in ("tone", "genre", "seat_range", "truth_events", "secrets",
                  "leak_surfaces", "relationships", "win_condition"):
        if field in review:
            updated[field] = review[field]
    if "truth_events" in review:
        updated["truth_events"] = []
        for item in review["truth_events"]:
            event = dict(item)
            quote = event.pop("source_quote", None)
            if quote and source_text:
                start = source_text.find(quote)
                if start < 0:
                    raise ValueError(f"source quote for {event['event_id']} was not found")
                key = f"truth_events.{event['event_id']}"
                updated["provenance"][key] = {
                    "field_path": key,
                    "source_doc": updated["parser_meta"]["source_files"][0],
                    "source_span": [start, start + len(quote)],
                    "confidence": 0.7,
                }
            updated["truth_events"].append(event)
    for role_id in review.get("culprit_role_ids", []):
        updated["characters"][role_id]["is_culprit"] = True
    for role_id, goals in review.get("character_goals", {}).items():
        updated["characters"][role_id]["private_goals"] = goals
    for role_id, goals_by_act in review.get("character_goals_by_act", {}).items():
        scoped = updated["characters"][role_id].setdefault("private_goals_by_act", {})
        for act_id, goals in goals_by_act.items():
            scoped[act_id] = goals
    for role_id, profile in review.get("public_profiles", {}).items():
        updated["characters"][role_id]["public_profile"] = profile
    for act in updated["acts"]:
        act.update(review.get("acts", {}).get(act["act_id"], {}))
    for clue in updated["clues"].values():
        clue.update(review.get("clue_defaults", {}))
    for clue_id, patch in review.get("clue_links", {}).items():
        updated["clues"][clue_id].update(patch)
    if "act_clues" in review:
        valid_acts = {act["act_id"] for act in updated["acts"]}
        scopes: dict[str, list[str]] = {}
        for act_id, clue_ids in review["act_clues"].items():
            if act_id not in valid_acts:
                raise ValueError(f"unknown act for clue scope: {act_id}")
            for clue_id in clue_ids:
                if clue_id not in updated["clues"]:
                    raise ValueError(f"unknown clue for act scope: {clue_id}")
                scopes.setdefault(clue_id, []).append(act_id)
        for clue_id, act_ids in scopes.items():
            updated["clues"][clue_id]["act_available"] = act_ids
        updated["act_scope_reviewed"] = True
    if "act_scope_reviewed" in review:
        updated["act_scope_reviewed"] = bool(review["act_scope_reviewed"])
    act_order = {act["act_id"]: act["order"] for act in updated["acts"]}
    for location_id, location in updated["locations"].items():
        available = sorted({act_id for clue in updated["clues"].values()
                            if clue["location_id"] == location_id
                            for act_id in clue["act_available"] if act_id in act_order},
                           key=act_order.get)
        if available:
            location["act_availability"] = available
    for clue_id, item in review.get("additional_clues", {}).items():
        clue = dict(item)
        quote = clue.pop("source_quote", None)
        if quote and source_text:
            start = source_text.find(quote)
            if start < 0:
                raise ValueError(f"source quote for {clue_id} was not found")
            key = f"clues.{clue_id}"
            updated["provenance"][key] = {
                "field_path": key, "source_doc": updated["parser_meta"]["source_files"][0],
                "source_span": [start, start + len(quote)], "confidence": 0.7,
            }
        updated["clues"][clue_id] = clue
        location_id = clue["location_id"]
        updated["locations"][location_id]["capacity_per_act"] = max(
            updated["locations"][location_id]["capacity_per_act"],
            sum(candidate["location_id"] == location_id for candidate in updated["clues"].values()))
    for location_id, patch in review.get("locations", {}).items():
        updated["locations"].setdefault(location_id, {}).update(patch)
    for role_id, patch in review.get("knowledge", {}).items():
        updated["knowledge"][role_id].update(patch)
    for role_id, statement_ids in review.get("approved_statement_ids", {}).items():
        statements = updated["knowledge"][role_id]["statements"]
        known_ids = {item["statement_id"] for item in statements}
        if not set(statement_ids).issubset(known_ids):
            raise ValueError(f"unknown statement for {role_id}")
        for item in statements:
            if item["statement_id"] in statement_ids and not item.get("source_span"):
                raise ValueError(f"approved statement {item['statement_id']} lacks a source")
            item["approved"] = item["statement_id"] in statement_ids
    updated.pop("linter_report", None)
    script = Script.model_validate(updated)
    report = lint_script(script)
    updated["linter_report"] = report.model_dump()
    updated["difficulty"] = report.difficulty
    return updated


def merge_statement_candidates(current: dict, extracted: dict) -> dict:
    updated = json.loads(json.dumps(current, ensure_ascii=False))
    for role_id, new_role in extracted["characters"].items():
        if updated["characters"][role_id]["display_name"] != new_role["display_name"]:
            raise ValueError(f"role mapping changed for {role_id}")
        existing = {item["statement_id"]: item
                    for item in updated["knowledge"][role_id].get("statements", [])}
        candidates = extracted["knowledge"][role_id].get("statements", [])
        merged = [item | {"approved": existing.get(item["statement_id"], {}).get("approved", False)}
                  for item in candidates]
        merged.extend(item for key, item in existing.items()
                      if key not in {candidate["statement_id"] for candidate in candidates})
        updated["knowledge"][role_id]["statements"] = merged
    return updated
