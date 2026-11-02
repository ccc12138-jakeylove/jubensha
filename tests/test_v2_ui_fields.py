from jubensha.ui.library import _field_value, _set_field_value


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
