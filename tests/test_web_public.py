from fastapi.testclient import TestClient

from jubensha.web.app import build_show, create_show_app


def test_public_show_excludes_unearned_clues_and_truth(script):
    payload = build_show(script)
    assert "clues" not in payload
    assert "timeline" not in payload
    serialized = str(payload)
    assert all(clue.surface_text not in serialized for clue in script.clues.values())
    assert all(event.action not in serialized for event in script.truth_events)


def test_public_site_blocks_author_routes_without_token(tmp_path, monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.delenv("AUTHOR_TOKEN", raising=False)
    client = TestClient(create_show_app(dsn=str(tmp_path / "web.db")))
    assert client.get("/api/show/script").status_code == 200
    scripts = client.get("/api/show/scripts").json()
    assert len(scripts) == 1 and scripts[0]["script_id"] == "wugang_01"
    assert client.get("/api/show/script?script_id=unknown").status_code == 404
    assert client.post("/api/show/accuse", json={"suspect_id": "any"}).status_code == 404
    created = client.post("/api/games", json={})
    assert created.status_code == 200
    game_id = created.json()["game_id"]
    act = client.get(f"/api/show/games/{game_id}/act").json()
    assert act["act_id"] == "A1" and act["is_final"]
    assert client.get("/api/v2/scripts").status_code == 503

    monkeypatch.setenv("AUTHOR_TOKEN", "review-only-token")
    assert client.get("/api/v2/scripts").status_code == 401
    assert client.get("/api/v2/scripts", headers={
        "Authorization": "Bearer review-only-token"}).status_code == 200


def test_current_act_view_changes_without_exposing_future_act(tmp_path, monkeypatch):
    monkeypatch.delenv("API_TOKEN", raising=False)
    client = TestClient(create_show_app(
        fixture_path="fixtures/multiact_demo.json", dsn=str(tmp_path / "acts.db")))
    public = client.get("/api/show/script").json()
    assert public["act_title"] == "第一幕·遗嘱"
    assert "储藏室的保险柜被打开" not in str(public)
    game_id = client.post("/api/games", json={}).json()["game_id"]
    path = f"/api/games/{game_id}/turns"
    for payload in ({"action": "begin"}, {"action": "read_done"},
                    {"action": "enter_confront"},
                    {"action": "vote", "role_id": "R01", "motive": "猜测"},
                    {"action": "next_act"}):
        assert client.post(path, json=payload).status_code == 200
    act = client.get(f"/api/show/games/{game_id}/act").json()
    assert act["act_id"] == "A02"
    assert act["title"] == "第二幕·旧案"
    assert "储藏室的保险柜被打开" in act["narrative"]
    assert act["is_final"]
