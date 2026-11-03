from jubensha.ui.library import _field_value, _set_approvals, _set_field_value


def test_field_editor_updates_one_nested_role_without_changing_others():
    ir = {"characters": {"r1": {"role_id": "r1", "name": "A"},
                         "r2": {"role_id": "r2", "name": "B"}}}
    updated = _set_field_value(ir, "characters.r1", {"role_id": "r1", "name": "C"})
    assert _field_value(updated, "characters.r1")["name"] == "C"
    assert _field_value(updated, "characters.r2")["name"] == "B"
    assert _field_value(ir, "characters.r1")["name"] == "A"


def test_field_editor_updates_one_timeline_event():
    ir = {"truth_events": [{"event_id": "E1", "action": "first"},
                            {"event_id": "E2", "action": "second"}]}
    updated = _set_field_value(ir, "truth_events.E2", {"event_id": "E2", "action": "revised"})
    assert _field_value(updated, "truth_events.E2")["action"] == "revised"
    assert _field_value(updated, "truth_events.E1")["action"] == "first"


def test_statement_approval_changes_only_selected_role():
    ir = {"knowledge": {
        "R01": {"statements": [{"statement_id": "KR01_01", "text": "A", "approved": False}]},
        "R02": {"statements": [{"statement_id": "KR02_01", "text": "B", "approved": False}]},
    }}
    updated = _set_approvals(ir, "R01", {"KR01_01": True})
    assert updated["knowledge"]["R01"]["statements"][0]["approved"]
    assert not updated["knowledge"]["R02"]["statements"][0]["approved"]
    assert not ir["knowledge"]["R01"]["statements"][0]["approved"]
