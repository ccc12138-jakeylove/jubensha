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


def _role_acts(raw: dict) -> tuple[list[str], dict[str, list[dict]]]:
    if raw and all(re.fullmatch(r"第[一二三四五六七八九十\d]+幕", key) for key in raw):
        act_names = list(raw)
        names = list(dict.fromkeys(name for act in raw.values() for name in act))
        return act_names, {name: [raw[act].get(name, {}) for act in act_names] for name in names}
    return ["第一幕"], {name: [value] for name, value in raw.items()}


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
        goals = [part.get("Purpose", "").strip() for part in parts if isinstance(part, dict)
                 and isinstance(part.get("Purpose"), str) and part["Purpose"].strip()]
        characters[role_id] = {
            "role_id": role_id, "display_name": name, "is_culprit": False,
            "public_profile": f"{name}。", "private_goals": goals,
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
    for location_index, (location_name, items) in enumerate(clues_raw.items(), 1):
        if isinstance(items, dict):
            entries = [(str(key), value, "private") for key, value in items.items()]
        elif isinstance(items, list):
            entries = [(None, value, "public") for value in items]
        else:
            raise ValueError(f"clue group {location_name} must be a list or object")
        location_id = f"L{location_index:02d}"
        locations[location_id] = {"location_id": location_id, "display_name": location_name,
                                  "description": location_name, "searchable": True,
                                  "capacity_per_act": max(1, len(entries)),
                                  "act_availability": act_ids, "connected_to": []}
        for clue_name, item, visibility in entries:
            surface = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            clue_id = f"C{len(clues) + 1:03d}"
            clues[clue_id] = {"clue_id": clue_id,
                              "display_name": clue_name or surface.splitlines()[0][:24] or clue_id,
                              "surface_text": surface, "truth_value": "true",
                              "location_id": location_id, "act_available": act_ids,
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
    ir = {"script_id": script_id, "title": title, "genre": genre, "ir_version": "1.1",
          "tone": "悬疑", "seat_range": [1, len(roles)],
          "win_condition": {"type": "accuse", "required": ["culprit", "motive", "key_evidence"],
                            "partial_credit": True},
          "acts": acts, "characters": characters, "truth_events": [], "clues": clues,
          "locations": locations, "secrets": {}, "knowledge": knowledge,
          "relationships": [], "leak_surfaces": {}, "provenance": provenance,
          "tags": tags, "content_rating": suggested_rating(tags),
          "parser_meta": {"source_files": [str(path) for path in files],
                          "segments": [], "field_confidence": {},
                          "reconcile_warnings": ["真相事件和线索关联需由作者校对"]}}
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
    for role_id, profile in review.get("public_profiles", {}).items():
        updated["characters"][role_id]["public_profile"] = profile
    for act in updated["acts"]:
        act.update(review.get("acts", {}).get(act["act_id"], {}))
    for clue in updated["clues"].values():
        clue.update(review.get("clue_defaults", {}))
    for clue_id, patch in review.get("clue_links", {}).items():
        updated["clues"][clue_id].update(patch)
    for location_id, patch in review.get("locations", {}).items():
        updated["locations"].setdefault(location_id, {}).update(patch)
    for role_id, patch in review.get("knowledge", {}).items():
        updated["knowledge"][role_id].update(patch)
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
