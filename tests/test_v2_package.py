import json

from jubensha.compiler.package import apply_review, compile_package, merge_statement_candidates
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def write_package(tmp_path, *, two_acts=False):
    folder = tmp_path / "MIRAGE_测试本"
    inner = folder / "测试本"
    inner.mkdir(parents=True)
    role = {"Story": "你是甲，负责看守大厅和书房的出入口。", "Script": "你看到乙在晚宴之前进入了大厅。",
            "Purpose": "查明真相", "Performance": "短句", "Ability": "不能说谎"}
    roles = ({"第一幕": {"甲": role, "乙": role}, "第二幕": {"甲": role, "乙": role}}
             if two_acts else {"甲": role, "乙": role})
    (inner / "人物剧本.json").write_text(json.dumps(roles, ensure_ascii=False), encoding="utf-8")
    (inner / "线索.json").write_text(json.dumps({"大厅": ["桌上有一张便条", "门锁有划痕"]},
                                               ensure_ascii=False), encoding="utf-8")
    (folder / "_真相_GM专用.txt").write_text("甲在大厅发现了便条。", encoding="utf-8")
    return folder


def test_structured_package_preserves_roles_clues_and_source_spans(tmp_path):
    draft = compile_package(write_package(tmp_path))
    assert not draft.valid
    assert len(draft.ir["characters"]) == 2 and len(draft.ir["clues"]) == 2
    assert len(draft.ir["acts"]) == 1
    assert "甲" in draft.source_text
    assert draft.ir["provenance"]["characters.R01"]["source_doc"].endswith("人物剧本.json")
    assert any(item.field_path == "truth_events" for item in draft.review_items)


def test_multi_act_package_stays_unpublished_without_truth_and_rights(tmp_path):
    draft = compile_package(write_package(tmp_path, two_acts=True))
    assert len(draft.ir["acts"]) == 2
    events = EventStore(tmp_path / "packages.db")
    scripts = ScriptStore(events)
    upload_id = scripts.save_upload("manifest.json", b"{}", rights_source="unverified",
                                    rights_confirmed=False)
    script_id = scripts.save_draft(draft, upload_id)
    assert scripts.get_draft(script_id)["status"] == "draft"


def test_named_memory_clues_remain_private(tmp_path):
    folder = write_package(tmp_path)
    inner = folder / "测试本"
    (inner / "线索.json").write_text(json.dumps({"甲的回忆": {"旧信": "一封没有寄出的信"}},
                                               ensure_ascii=False), encoding="utf-8")
    draft = compile_package(folder)
    clue = next(iter(draft.ir["clues"].values()))
    assert clue["display_name"] == "旧信" and clue["visibility"] == "private"


def test_review_adds_truth_without_overwriting_source_draft(tmp_path):
    draft = compile_package(write_package(tmp_path))
    review = {"script_id": draft.ir["script_id"], "culprit_role_ids": ["R01"],
              "truth_events": [{"event_id": "E01", "act_id": "A01", "t_start": 0,
                                "t_end": 1, "location_id": "L01", "actor_ids": ["R01"],
                                "action": "甲留下便条", "observable": [], "hidden": [],
                                "evidence_clue_ids": ["C001"],
                                "source_quote": "甲在大厅发现了便条"}],
              "clue_defaults": {"act_available": ["A01"]},
              "clue_links": {"C001": {"reveals_event_ids": ["E01"]}}}
    updated = apply_review(draft.ir, review, draft.source_text)
    assert updated["linter_report"]["passed"]
    assert draft.ir["truth_events"] == []
    assert "truth_events.E01" in updated["provenance"]


def test_statement_refresh_preserves_author_approval(tmp_path):
    draft = compile_package(write_package(tmp_path))
    prior = draft.ir
    prior["knowledge"]["R01"]["statements"][0]["approved"] = True
    refreshed = compile_package(tmp_path / "MIRAGE_测试本")
    merged = merge_statement_candidates(prior, refreshed.ir)
    assert merged["knowledge"]["R01"]["statements"][0]["approved"]
