import io
import json

import pytest
from docx import Document

from jubensha.compiler.ingest import read_document, segment_document
from jubensha.compiler.content import fingerprint_match, pii_hits, simhash, suggested_rating
from jubensha.compiler.lint import lint_script
from jubensha.compiler.report import render_lint_report
from jubensha.compiler.pipeline import EXTRACT_FIELDS, ExtractionError, ReviewItem, _extract_field, _extract_role_pages, _item_provenance, _normalize_container, _parse_json_response, _select_excerpt, compile_document
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


def test_pdf_page_markers_keep_page_numbers_in_segments():
    segments = segment_document("case.pdf", "# Page 1\nOpening\n# Page 2\nClue table")
    assert [item.page_number for item in segments] == [1, 2]


def test_role_pages_extract_separate_characters(script, tmp_path, monkeypatch):
    segments = segment_document("case.pdf", "# Page 1\nWHO YOU ARE\nRole one\n# Page 2\nWHO YOU ARE\nRole two")
    roles = list(script.characters.values())[:2]
    def mock_generate(store, trace_id, node, version, messages, max_tokens=1600, json_mode=False):
        index = 0 if "Page 1" in messages[-1]["content"] else 1
        return json.dumps({"value": roles[index].model_dump(mode="json")}, ensure_ascii=False)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    extracted, confidence, span, repaired = _extract_role_pages(
        segments, EventStore(tmp_path / "roles.db"), "test")
    assert set(extracted) == {role.role_id for role in roles}
    assert confidence == 0.5 and repaired and span[0] == 0


def test_item_provenance_points_to_character_page(script):
    text = "# Page 1\nOpening\n# Page 2\n林素云 lives at the inn."
    segments = segment_document("case.pdf", text)
    role = script.characters["lin_suyun"].model_dump(mode="json")
    provenance = _item_provenance("characters", {"lin_suyun": role}, text,
                                  segments, "case.pdf", 0.5)
    assert provenance["characters.lin_suyun"]["source_page"] == 2
    start, end = provenance["characters.lin_suyun"]["source_span"]
    assert text[start:end] == "林素云"


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
    assert caught.value.raw_response


def test_field_retry_includes_previous_response_and_lowers_confidence(tmp_path, monkeypatch):
    calls = []
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000, json_mode=False):
        calls.append(messages)
        return '{"value": {"wrong": true}}' if len(calls) == 1 else '{"value": "Case title", "confidence": 0.9}'
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    value, confidence, _, repaired = _extract_field(
        "title", segment_document("case.txt", "Case title"), EventStore(tmp_path / "retry.db"), "test")
    assert value == "Case title" and confidence == 0.5 and repaired
    assert calls[1][-2]["role"] == "assistant"


def test_linter_detects_dead_script(script):
    baseline = lint_script(script)
    assert baseline.solvability.optimal_path_clue_ids
    assert any(item.code == "KEY_CHAIN_RESOURCE_RISK" for item in baseline.warnings)
    assert baseline.solvability.minimum_cost is not None
    assert baseline.solvability.minimum_cost <= baseline.solvability.search_budget
    assert "最短关键证据路径" in render_lint_report(script, baseline)
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


def test_linter_detects_multiple_culprits_and_unaffordable_path(script):
    multiple = script.model_copy(deep=True)
    multiple.characters["a_dai"].is_culprit = True
    report = lint_script(multiple)
    assert any(item.code == "MULTIPLE_CULPRITS" for item in report.blockers)
    costly = script.model_copy(deep=True)
    for clue in costly.clues.values():
        clue.search_cost = 10
    report = lint_script(costly)
    assert any(item.code == "BUDGET_UNSOLVABLE" for item in report.blockers)
    thresholds = script.model_copy(deep=True)
    thresholds.acts[0].director_proactive_after = 12
    thresholds.acts[0].director_hint_after = 8
    thresholds.acts[0].director_critical_after = 16
    assert any(item.code == "INVALID_DIRECTOR_THRESHOLDS"
               for item in lint_script(thresholds).blockers)
    unsupported = script.model_copy(deep=True)
    culprit = next(role for role in unsupported.characters.values() if role.is_culprit)
    culprit.private_goals = ["蓝鲸跃入星河"]
    assert any(item.code == "MISSING_MOTIVE_SUPPORT"
               for item in lint_script(unsupported).warnings)


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


def test_ir_11_metadata_is_optional_for_10_fixture(script, tmp_path):
    assert script.ir_version == "1.0"
    upgraded = script.model_copy(update={"ir_version": "1.1", "difficulty": 3,
                                         "content_rating": "12+", "tags": ["推理"]})
    assert upgraded.difficulty == 3
    store = ScriptStore(EventStore(tmp_path / "metadata.db"))
    store.register_fixture(script)
    with store.events.connect() as db:
        before = db.execute("SELECT content_hash FROM scripts WHERE script_id=?",
                            (script.script_id,)).fetchone()[0]
    store.register_fixture(upgraded)
    with store.events.connect() as db:
        after = db.execute("SELECT ir_version,content_hash,difficulty FROM scripts WHERE script_id=?",
                           (script.script_id,)).fetchone()
        versions = db.execute("SELECT count(*) FROM script_versions WHERE script_id=?",
                              (script.script_id,)).fetchone()[0]
    assert after[0] == "1.1" and after[1] != before and after[2] == 3
    assert versions == 2


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


def test_long_document_scans_every_segment_before_assembly(script, tmp_path, monkeypatch):
    calls = []
    source = script.model_dump(mode="json")
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000, json_mode=False):
        if node == "compiler_segment":
            calls.append(messages[-1]["content"])
            return json.dumps({"characters": ["visible role"], "clues": ["visible clue"]})
        field = version.split(".")[-2]
        return json.dumps({"value": source[field], "confidence": 0.9,
                           "source_span": [0, 10]}, ensure_ascii=False)
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: True)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    text = "Opening and clues. " * 1000
    result = compile_document("long.txt", text.encode(), EventStore(tmp_path / "long.db"))
    assert result.valid
    assert len(calls) == len(result.segments)
    assert all(item["entities"]["clues"] == ["visible clue"]
               for item in result.ir["parser_meta"]["segments"])


def test_missing_scalar_metadata_uses_reviewable_defaults(script, tmp_path, monkeypatch):
    source = script.model_dump(mode="json")
    def mock_generate(store, trace_id, node, version, messages, max_tokens=4000, json_mode=False):
        field = version.split(".")[-2]
        value = None if field in {"script_id", "title", "genre", "ir_version", "tone"} else source[field]
        return json.dumps({"value": value}, ensure_ascii=False)
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: True)
    monkeypatch.setattr("jubensha.compiler.pipeline.generate", mock_generate)
    result = compile_document("strange.md", b"A murder mystery", EventStore(tmp_path / "defaults.db"))
    assert result.valid
    assert result.ir["script_id"] == "strange"
    assert result.ir["genre"] == "本格" and result.ir["ir_version"] == "1.1"
    assert any(item.field_path == "genre" and item.conflict_type == "low_confidence"
               for item in result.review_items)


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


def test_upload_and_text_limits_are_enforced(tmp_path):
    store = EventStore(tmp_path / "limits.db")
    scripts = ScriptStore(store)
    with pytest.raises(ValueError, match="10 MB"):
        scripts.save_upload("huge.txt", b"x" * 10_000_001)
    with pytest.raises(ValueError, match="300000"):
        compile_document("long.txt", b"x" * 300_001, store)


def test_content_rating_is_visible_in_review(tmp_path, monkeypatch):
    monkeypatch.setattr("jubensha.compiler.pipeline.configured", lambda: False)
    result = compile_document("horror.txt", "旅馆里有血腥的尸块。".encode(),
                              EventStore(tmp_path / "game.db"))
    assert any(item.conflict_type == "content_rating" and "血腥" in item.message
               for item in result.review_items)
    assert any(not item.resolved for item in result.review_items
               if item.conflict_type == "content_rating")


def test_pii_and_similarity_enter_review_queue(script, tmp_path):
    assert pii_hits("联系 13812345678 或 writer@example.com") == ["phone", "email"]
    assert pii_hits("身份证 110101199001011234") == ["national_id"]
    assert pii_hits("北京市海淀区中关村路12号") == ["address"]
    assert pii_hits("联系人：张三") == ["labeled_name"]
    assert suggested_rating(["恐怖", "暴力"]) == "16+"
    assert fingerprint_match(simhash("同一段故事" * 80), simhash("同一段故事" * 80))
    store = EventStore(tmp_path / "content.db")
    scripts = ScriptStore(store)
    first = script.model_dump(mode="json") | {"script_id": "first_case"}
    second = script.model_dump(mode="json") | {"script_id": "second_case"}
    first_draft = compile_document("first.json", json.dumps(first, ensure_ascii=False).encode(), store)
    second_draft = compile_document("second.json", json.dumps(second, ensure_ascii=False).encode(), store)
    scripts.save_draft(first_draft)
    scripts.save_draft(second_draft)
    assert any(item.conflict_type == "copyright_similarity"
               for _, item, _ in scripts.reviews("second_case"))
    with pytest.raises(ValueError, match="review items"):
        scripts.publish("second_case")


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


def test_partial_draft_can_be_saved_and_rolled_back(script, tmp_path):
    store = EventStore(tmp_path / "partial.db")
    scripts = ScriptStore(store)
    draft = compile_document("case.json", script.model_dump_json().encode(), store)
    script_id = scripts.save_draft(draft)
    partial = scripts.get_draft(script_id)["ir"]
    partial.pop("clues")
    scripts.update_ir(script_id, json.dumps(partial, ensure_ascii=False))
    assert "clues" not in scripts.get_draft(script_id)["ir"]
    assert any(item.conflict_type == "schema_error" for _, item, _ in scripts.reviews(script_id))
    with pytest.raises(ValueError):
        scripts.publish(script_id)
    revision_id = scripts.revisions(script_id)[0]["revision_id"]
    scripts.rollback(script_id, revision_id)
    assert "clues" in scripts.get_draft(script_id)["ir"]


def test_unconfirmed_package_rights_block_publication(script, tmp_path):
    store = EventStore(tmp_path / "rights.db")
    scripts = ScriptStore(store)
    upload_id = scripts.save_upload("bundle.json", b"{}", rights_source="unverified package",
                                    rights_confirmed=False)
    draft = compile_document("case.json", script.model_dump_json().encode(), store)
    scripts.save_draft(draft, upload_id)
    with pytest.raises(ValueError, match="usage rights"):
        scripts.publish(script.script_id)
    scripts.confirm_rights(upload_id, "author license documented")
    assert scripts.publish(script.script_id).script_id == script.script_id


def test_local_only_package_cannot_be_confirmed_or_published(script, tmp_path):
    store = EventStore(tmp_path / "local_only.db")
    scripts = ScriptStore(store)
    upload_id = scripts.save_upload("bundle.json", b"{}", rights_source="local verification only",
                                    rights_confirmed=False, distribution_scope="local_only")
    draft = compile_document("case.json", script.model_dump_json().encode(), store)
    scripts.save_draft(draft, upload_id)
    with pytest.raises(ValueError, match="local-only"):
        scripts.confirm_rights(upload_id, "claimed license")
    with pytest.raises(ValueError, match="usage rights"):
        scripts.publish(script.script_id)
    with store.connect() as db:
        row = db.execute("SELECT authorized_at,distribution_scope FROM script_uploads WHERE upload_id=?",
                         (upload_id,)).fetchone()
    assert row["authorized_at"] is None
    assert row["distribution_scope"] == "local_only"
    scripts.authorize_draft(script.script_id, "user explicitly authorized use and publication")
    assert scripts.publish(script.script_id).script_id == script.script_id


def test_authorized_structural_draft_can_preview_without_publication(script, tmp_path):
    store = EventStore(tmp_path / "preview.db")
    scripts = ScriptStore(store)
    upload_id = scripts.save_upload("case.json", b"{}", rights_source="user authorization")
    draft = compile_document("case.json", script.model_dump_json().encode(), store)
    scripts.save_draft(draft, upload_id)
    assert scripts.load_preview(script.script_id).script_id == script.script_id
    store.create_game("preview", script.script_id, script.acts[0].act_id, is_preview=True)
    store.create_game("ordinary", script.script_id, script.acts[0].act_id)
    assert store.is_preview_game("preview") and not store.is_preview_game("ordinary")
    assert EventStore(tmp_path / "preview.db").is_preview_game("preview")
    with pytest.raises(ValueError, match="not published"):
        scripts.load_published(script.script_id)
