import json

from jubensha.compiler.lint import lint_script
from jubensha.compiler.package import apply_review, compile_package
from jubensha.engine.perception import build_perception
from jubensha.schema.state import GameState, SeatState


def write_multiact_package(tmp_path, *, grouped_clues: bool):
    folder = tmp_path / "MIRAGE_双幕测试本"
    inner = folder / "双幕测试本"
    inner.mkdir(parents=True)
    first = {
        "甲": {"Story": "甲在书房见过乙。", "Script": "甲在书房整理遗嘱。",
               "Purpose": "确认遗嘱内容", "Performance": "克制", "Ability": "不说谎"},
        "乙": {"Story": "乙在走廊听见争吵。", "Script": "乙看见甲进了书房。",
               "Purpose": "查明父亲死因", "Performance": "急切", "Ability": "不隐瞒"},
    }
    second = {
        "甲": {"Story": "甲承认自己改过遗嘱。", "Script": "甲把新遗嘱藏进保险柜。",
               "Purpose": "掩盖自己改写遗嘱的事实", "Performance": "克制", "Ability": "不说谎"},
        "乙": {"Story": "乙找到了保险柜钥匙。", "Script": "乙打开了储藏室。",
               "Purpose": "查明父亲死因", "Performance": "急切", "Ability": "不隐瞒"},
    }
    (inner / "人物剧本.json").write_text(
        json.dumps({"第一幕": first, "第二幕": second}, ensure_ascii=False), encoding="utf-8")
    clues = ({
        "第一幕线索": {"书房": ["遗嘱草案的受益人一栏有涂改"]},
        "第二幕线索": {"储藏室": ["保险柜里有一份新遗嘱"]},
    } if grouped_clues else {
        "书房": ["遗嘱草案的受益人一栏有涂改"],
        "储藏室": ["保险柜里有一份新遗嘱"],
    })
    (inner / "线索.json").write_text(json.dumps(clues, ensure_ascii=False), encoding="utf-8")
    (folder / "_真相_GM专用.txt").write_text("甲在第二幕改写了遗嘱。", encoding="utf-8")
    return folder


def test_multi_act_goals_are_scoped_and_later_goals_do_not_leak(tmp_path):
    draft = compile_package(write_multiact_package(tmp_path, grouped_clues=True))
    assert len(draft.ir["acts"]) == 2
    character = draft.ir["characters"]["R01"]
    assert character["private_goals"] == ["确认遗嘱内容"]
    assert character["private_goals_by_act"] == {
        "A01": ["确认遗嘱内容"], "A02": ["掩盖自己改写遗嘱的事实"]}
    script = draft.ir
    assert script["clues"]["C001"]["act_available"] == ["A01"]
    assert script["clues"]["C002"]["act_available"] == ["A02"]
    assert script["locations"]["L01"]["act_availability"] == ["A01"]
    assert script["locations"]["L02"]["act_availability"] == ["A02"]
    assert not script["act_scope_reviewed"]


def test_ungrouped_clues_are_conservatively_scoped_to_first_act(tmp_path):
    draft = compile_package(write_multiact_package(tmp_path, grouped_clues=False))
    assert all(clue["act_available"] == ["A01"] for clue in draft.ir["clues"].values())
    assert all(location["act_availability"] == ["A01"]
               for location in draft.ir["locations"].values())
    assert any("保守归入第一幕" in warning
               for warning in draft.ir["parser_meta"]["reconcile_warnings"])
    assert any(item.field_path == "act_scope" for item in draft.review_items)
    warning_codes = {item["code"] for item in draft.ir["linter_report"]["warnings"]}
    assert "MULTI_ACT_SCOPE_UNREVIEWED" in warning_codes


def test_review_can_scope_clues_per_act_and_clears_scope_warning(tmp_path):
    draft = compile_package(write_multiact_package(tmp_path, grouped_clues=False))
    updated = apply_review(draft.ir, {
        "script_id": draft.ir["script_id"],
        "act_clues": {"A01": ["C001"], "A02": ["C002"]},
    }, draft.source_text)
    assert updated["act_scope_reviewed"]
    assert updated["clues"]["C001"]["act_available"] == ["A01"]
    assert updated["clues"]["C002"]["act_available"] == ["A02"]
    assert updated["locations"]["L01"]["act_availability"] == ["A01"]
    assert updated["locations"]["L02"]["act_availability"] == ["A02"]
    warning_codes = {item["code"] for item in updated["linter_report"]["warnings"]}
    assert "MULTI_ACT_SCOPE_UNREVIEWED" not in warning_codes


def test_perception_hides_later_act_goals(tmp_path):
    draft = compile_package(write_multiact_package(tmp_path, grouped_clues=True))
    from jubensha.schema.ir import Script
    script = Script.model_validate(draft.ir)
    state = GameState(game_id="g", script_id=script.script_id, act_id="A01",
                      seats={"seat_1": SeatState(seat_id="seat_1")})
    first = build_perception(script, state, "R01")
    assert first.private_goals == ["确认遗嘱内容"]
    state.act_id = "A02"
    second = build_perception(script, state, "R01")
    assert "掩盖自己改写遗嘱的事实" in second.private_goals


def test_lint_warns_when_multi_act_goals_are_not_split_by_act(script):
    script = script.model_copy(deep=True)
    script.acts.append(script.acts[0].model_copy(update={
        "act_id": "A2", "order": 2, "title": "第二幕"}))
    assert any(character.private_goals for character in script.characters.values())
    assert not any(character.private_goals_by_act for character in script.characters.values())
    report = lint_script(script)
    codes = {item.code for item in report.warnings}
    assert "MULTI_ACT_GOAL_SCOPE_UNREVIEWED" in codes


def test_lint_blocks_clue_that_reveals_a_later_act(script):
    script = script.model_copy(deep=True)
    script.acts.append(script.acts[0].model_copy(update={
        "act_id": "A2", "order": 2, "title": "第二幕"}))
    script.truth_events[0] = script.truth_events[0].model_copy(update={"act_id": "A2"})
    script.clues["C01"] = script.clues["C01"].model_copy(
        update={"act_available": ["A1"], "reveals_event_ids": ["E01"]})
    report = lint_script(script)
    assert "CLUE_REVEALS_LATER_ACT" in {item.code for item in report.blockers}
