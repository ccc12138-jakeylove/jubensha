import io
import json

import pytest
from docx import Document

from jubensha.compiler.ingest import read_document, segment_document
from jubensha.compiler.lint import lint_script
from jubensha.compiler.pipeline import EXTRACT_FIELDS, ExtractionError, ReviewItem, _extract_field, _normalize_container, _parse_json_response, _select_excerpt, compile_document
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def test_ingest_text_and_docx():
    text = "# 角色本\n阿黛知道一些事。\n# 线索表\n门闩完好。"
    segments = segment_document("case.md", read_document("case.md", text.encode()))
    assert {segment.kind for segment in segments} == {"character", "clue"}
    document = Document()
    document.add_heading("旅馆里的线索", level=1)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "线索编号"
    table.cell(0, 1).text = "门闩完好"
    stream = io.BytesIO()
    document.save(stream)
    extracted = read_document("case.docx", stream.getvalue())
    assert "# 旅馆里的线索" in extracted
    assert "线索编号 | 门闩完好" in extracted


def test_extract_selection_can_reach_end_of_long_script():
    text = "# 开场\n" + "普通叙述。" * 3000 + "\n# 真相\n凶手结局在最后。"
    segments = segment_document("long.md", text)
    assert "凶手结局在最后" in _select_excerpt("truth_events", segments)


def test_clue_selection_keeps_host_solution_across_tail_segments():
    segments = segment_document("long.txt", "Opening. " * 700 + "First clue in host notes. "
                                + "Filler. " * 500 + "Final clue in host notes.", max_chars=3000)
    excerpt = _select_excerpt("clues", segments, max_chars=6500)
    assert "First clue in host notes" in excerpt
    assert "Final clue in host notes" in excerpt


def test_syntax_repair_is_explicit():
    result, repaired = _parse_json_response('{"value": {"A": 1 "B": 2}}')
    assert repaired
    assert result["value"]["A"] == 1


def test_id_keyed_list_can_be_normalized_without_new_facts():
    value, normalized = _normalize_container("characters", [{"role_id": "r1"}, {"role_id": "r2"}])
    assert normalized and set(value) == {"r1", "r2"}
    with pytest.raises(ValueError, match="duplicate"):
        _normalize_container("characters", [{"role_id": "r1"}, {"role_id": "r1"}])


def test_invalid_field_keeps_partial_result_for_review(tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", lambda *args, **kwargs:
                        json.dumps({"value": [{"clue_id": "C1", "surface_text": "A marked cup"}]}))
    segments = segment_document("case.txt", "A marked cup")
    with pytest.raises(ExtractionError) as caught:
        _extract_field("clues", segments, EventStore(tmp_path / "game.db"), "test")
    assert caught.value.partial["C1"]["surface_text"] == "A marked cup"


def test_linter_detects_dead_script(script):
    baseline = lint_script(script)
    assert baseline.solvability.optimal_path_clue_ids
    assert any(item.code == "KEY_CHAIN_RESOURCE_RISK" for item in baseline.warnings)
    assert all(set(script.clues[key].prerequisites).issubset(
        set(baseline.solvability.optimal_path_clue_ids))
        for key in baseline.solvability.optimal_path_clue_ids)
    script.clues["C09"].prerequisites = ["MISSING"]
    report = lint_script(script)
    assert not report.passed
    assert any(issue.code == "UNREACHABLE_CLUE" for issue in report.blockers)
    script.truth_events[2].t_start = -89
    report = lint_script(script)
    assert any(issue.code == "TIMELINE_CONFLICT" for issue in report.blockers)


def test_linter_rejects_cross_reference_errors(script):
    broken = script.model_copy(deep=True)
    role_id = next(iter(broken.knowledge))
    broken.knowledge[role_id].knows_event_ids.append("E99")
    assert any(item.code == "BROKEN_KNOWLEDGE_REFERENCE" for item in lint_script(broken).blockers)
    broken = script.model_copy(deep=True)
    broken.locations["dock"].connected_to.append("missing_room")
    assert any(item.code == "BROKEN_LOCATION_REFERENCE" for item in lint_script(broken).blockers)
    broken = script.model_copy(deep=True)
    broken.secrets["S01"].owner_role_id = "zhou_shen"
    assert any(item.code == "BROKEN_SECRET_OWNER" for item in lint_script(broken).blockers)
    broken = script.model_copy(deep=True)
    broken.truth_events[0].t_start = 24000
    assert any(item.code == "UNUSUAL_TIME_OFFSET" for item in lint_script(broken).warnings)


def test_json_draft_requires_review_and_can_publish(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    drafts = ScriptStore(store)
    content = script.model_dump_json().encode()
    result = compile_document("case.json", content, store)
    assert result.valid
    script_id = drafts.save_draft(result)
    published = drafts.publish(script_id)
    assert published.script_id == script.script_id
    assert drafts.load_published(script_id).title == script.title


def test_natural_language_extracts_by_schema(script, tmp_path, monkeypatch):
    store = EventStore(tmp_path / "game.db")
    source = script.model_dump(mode="json")
    fields = iter(EXTRACT_FIELDS)
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000, json_mode=False):
        field = next(fields)
        assert field in version
        assert json_mode
        return json.dumps({"value": source[field], "confidence": 0.9, "source_span": [0, 12]},
                          ensure_ascii=False)
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: True)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    result = compile_document("strange.md", "# 角色本\n一段陌生剧本文字".encode(), store)
    assert result.valid
    assert set(result.ir["provenance"]) == set(EXTRACT_FIELDS)


def test_compile_draft_keeps_invalid_clues_but_blocks_publication(script, tmp_path, monkeypatch):
    source = script.model_dump(mode="json")
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000, json_mode=False):
        field = version.split(".")[-2]
        value = [{"clue_id": "C1", "surface_text": "A marked cup"}] if field == "clues" else source[field]
        return json.dumps({"value": value, "confidence": 0.9, "source_span": [0, 12]})
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: True)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    store = EventStore(tmp_path / "game.db")
    result = compile_document("case.txt", b"A marked cup", store)
    assert not result.valid
    assert result.ir["clues"]["C1"]["surface_text"] == "A marked cup"
    assert any(item.field_path == "clues" and item.conflict_type == "parse_error"
               for item in result.review_items)


def test_no_model_produces_reviewable_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: False)
    result = compile_document("strange.txt", "只有自然语言。".encode(), EventStore(tmp_path / "game.db"))
    assert not result.valid
    assert any(item.conflict_type == "missing_model" for item in result.review_items)


def test_content_rating_is_visible_in_review(tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: False)
    result = compile_document("horror.txt", "旅馆里有血腥的尸块。".encode(),
                              EventStore(tmp_path / "game.db"))
    assert any(item.conflict_type == "content_rating" and "血腥" in item.message
               for item in result.review_items)


def test_unusual_time_requires_human_confirmation(script, tmp_path):
    script.truth_events[0].t_start = 24000
    script.truth_events[0].t_end = 24001
    store = EventStore(tmp_path / "game.db")
    result = compile_document("case.json", script.model_dump_json().encode(), store)
    assert any(item.conflict_type == "linter_warning" for item in result.review_items)
    drafts = ScriptStore(store)
    script_id = drafts.save_draft(result)
    with pytest.raises(ValueError, match="review items"):
        drafts.publish(script_id)


def test_publish_gate_requires_review_and_no_blockers(script, tmp_path):
    store = EventStore(tmp_path / "game.db")
    drafts = ScriptStore(store)
    result = compile_document("case.json", script.model_dump_json().encode(), store)
    result.review_items.append(ReviewItem(field_path="title", confidence=0.5,
                                          conflict_type="low_confidence", message="核对标题"))
    script_id = drafts.save_draft(result)
    with pytest.raises(ValueError, match="review items"):
        drafts.publish(script_id)
    item_id = next(item_id for item_id, item, _ in drafts.reviews(script_id)
                   if item.conflict_type == "low_confidence")
    drafts.resolve(script_id, item_id)
    broken = script.model_copy(deep=True)
    broken.clues["C09"].prerequisites = ["MISSING"]
    drafts.update_ir(script_id, broken.model_dump_json())
    with pytest.raises(ValueError, match="linter blockers"):
        drafts.publish(script_id)
    drafts.update_ir(script_id, script.model_dump_json())
    assert drafts.publish(script_id).script_id == script_id
