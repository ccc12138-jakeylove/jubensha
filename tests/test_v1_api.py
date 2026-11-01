import json

from fastapi.testclient import TestClient

from jubensha.api.app import create_app


def test_api_game_and_recap(tmp_path, script):
    client = TestClient(create_app(str(tmp_path / "api.db")))
    game_id = client.post("/api/games", json={"script_id": script.script_id}).json()["game_id"]
    assert client.get(f"/api/games/{game_id}/report").status_code == 403
    def turn(action, **kwargs):
        response = client.post(f"/api/games/{game_id}/turns", json={"action": action, **kwargs})
        assert response.status_code == 200, response.text
        return response.json()
    turn("begin")
    turn("read_done")
    turn("talk", role_id="lin_suyun", text="你在哪里？")
    turn("enter_search")
    turn("search", location_id="room_201", clue_id="C04")
    assert [item["clue_id"] for item in client.get(f"/api/games/{game_id}/clues").json()] == ["C04"]
    turn("leave_search")
    turn("enter_confront")
    judgment = client.post(f"/api/games/{game_id}/adjudicate",
                           json={"action": "vote", "role_id": "lin_suyun",
                                 "motive": "欠条", "evidence_ids": ["C04"]})
    assert judgment.status_code == 200
    assert judgment.json()["passed"]
    turn("recap")
    assert client.get(f"/api/games/{game_id}/report").status_code == 200
    assert client.get(f"/api/games/{game_id}/replay?seq=0").json()["state"]["turn"] == 0
    assert "data:" in client.post(f"/api/games/{game_id}/turns?stream=true",
                                  json={"action": "end"}).text


def test_api_upload_review_publish(tmp_path, script):
    client = TestClient(create_app(str(tmp_path / "api.db")))
    payload = script.model_dump(mode="json")
    payload["script_id"] = "api_upload_test"
    denied = client.post("/api/scripts", data={"authorized": "false"},
                         files={"file": ("case.json", json.dumps(payload).encode())})
    assert denied.status_code == 422
    upload = client.post("/api/scripts", data={"authorized": "true"},
                         files={"file": ("case.json", json.dumps(payload).encode())})
    assert upload.status_code == 200
    upload_id = upload.json()["upload_id"]
    compiled = client.post(f"/api/scripts/{upload_id}/compile")
    assert compiled.status_code == 200
    script_id = compiled.json()["script_id"]
    review = client.get(f"/api/scripts/{script_id}/review")
    assert review.status_code == 200
    assert review.json()["ir"]["script_id"] == script_id
    assert client.post(f"/api/scripts/{script_id}/publish").status_code == 200
    assert client.post("/api/games", json={"script_id": script_id}).status_code == 200


def test_api_token_can_protect_local_service(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    client = TestClient(create_app(str(tmp_path / "api.db")))
    assert client.post("/api/games", json={}).status_code == 401
    assert client.post("/api/games", json={}, headers={"Authorization": "Bearer test-token"}).status_code == 200
