import io
import json

import pytest
from docx import Document

from jubensha.compiler.ingest import read_document, segment_document
from jubensha.compiler.lint import lint_script
from jubensha.compiler.pipeline import EXTRACT_FIELDS, ReviewItem, compile_document
from jubensha.storage.events import EventStore
from jubensha.storage.scripts import ScriptStore


def test_ingest_text_and_docx():
    text = "# 角色本\n阿黛知道一些事。\n# 线索表\n门闩完好。"
    segments = segment_document("case.md", read_document("case.md", text.encode()))
    assert {segment.kind for segment in segments} == {"character", "clue"}
    document = Document()
    document.add_paragraph("旅馆里的线索")
    stream = io.BytesIO()
    document.save(stream)
    assert "线索" in read_document("case.docx", stream.getvalue())


def test_linter_detects_dead_script(script):
    baseline = lint_script(script)
    assert baseline.solvability.optimal_path_clue_ids
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
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000):
        field = next(fields)
        assert field in version
        return json.dumps({"value": source[field], "confidence": 0.9, "source_span": [0, 12]},
                          ensure_ascii=False)
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: True)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    result = compile_document("strange.md", "# 角色本\n一段陌生剧本文字".encode(), store)
    assert result.valid
    assert set(result.ir["provenance"]) == set(EXTRACT_FIELDS)


def test_no_model_produces_reviewable_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: False)
    result = compile_document("strange.txt", "只有自然语言。".encode(), EventStore(tmp_path / "game.db"))
    assert not result.valid
    assert any(item.conflict_type == "missing_model" for item in result.review_items)


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
