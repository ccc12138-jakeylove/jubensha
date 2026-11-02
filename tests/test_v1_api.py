import json
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from jubensha.api.app import create_app
from jubensha.eval.metrics import EvalMetrics
from jubensha.storage.events import EventStore


def test_api_game_and_recap(tmp_path, script, monkeypatch):
    client = TestClient(create_app(str(tmp_path / "api.db")))
    game_id = client.post("/api/games", json={"script_id": script.script_id}).json()["game_id"]
    assert client.get(f"/api/games/{game_id}/report").status_code == 403
    assert client.get(f"/api/v2/games/{game_id}/recap").status_code == 403
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
    recap = client.get(f"/api/v2/games/{game_id}/recap")
    assert recap.status_code == 200
    assert "missing_clue_ids" in recap.json() and "first_found_turn" in recap.json()
    assert client.get(f"/api/games/{game_id}/replay?seq=0").json()["state"]["turn"] == 0
    assert client.get(f"/api/games/{game_id}/replay", params={"perspective": "lin_suyun"}).status_code == 403
    monkeypatch.setenv("AUTHOR_TOKEN", "author-secret")
    author_view = client.get(f"/api/games/{game_id}/replay", params={"perspective": "lin_suyun"},
                             headers={"X-Author-Token": "author-secret"})
    assert author_view.status_code == 200
    stream = client.post(f"/api/games/{game_id}/turns?stream=true",
                         json={"action": "end"}).text
    assert "event: node_start" in stream and "event: node_end" in stream
    assert "event: token" in stream and "event: done" in stream


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
    game = client.post("/api/games", json={"script_id": script_id})
    assert game.status_code == 200
    listed = client.get("/api/v2/scripts", params={"status": "published", "genre": "本格"})
    assert any(item["script_id"] == script_id for item in listed.json())
    assert client.get(f"/api/v2/scripts/{script_id}/versions").json()["versions"]
    assert client.post(f"/api/v2/scripts/{script_id}/archive").status_code == 200
    assert client.post("/api/games", json={"script_id": script_id}).status_code == 404
    assert client.get(f"/api/games/{game.json()['game_id']}").status_code == 200
    assert client.delete(f"/api/v2/scripts/{script_id}").status_code == 422


def test_api_token_can_protect_local_service(tmp_path, monkeypatch):
    monkeypatch.setenv("API_TOKEN", "test-token")
    client = TestClient(create_app(str(tmp_path / "api.db")))
    assert client.post("/api/games", json={}).status_code == 401
    assert client.post("/api/games", json={}, headers={"Authorization": "Bearer test-token"}).status_code == 200


def test_v2_compile_job_is_async_and_idempotent(tmp_path, script):
    client = TestClient(create_app(str(tmp_path / "jobs.db")))
    payload = script.model_dump(mode="json") | {"script_id": "async_case"}
    upload = client.post("/api/v2/scripts", data={"authorized": "true", "rights_source": "author original"},
                         files={"file": ("case.json", json.dumps(payload).encode())})
    assert upload.status_code == 200
    upload_id = upload.json()["upload_id"]
    headers = {"Idempotency-Key": "case-upload-1"}
    first = client.post("/api/v2/compile-jobs", json={"upload_id": upload_id}, headers=headers)
    assert first.status_code == 202
    second = client.post("/api/v2/compile-jobs", json={"upload_id": upload_id}, headers=headers)
    assert second.json()["job_id"] == first.json()["job_id"]
    assert client.post("/api/v2/compile-jobs", json={"upload_id": "missing"}).status_code == 404
    bad = client.post("/api/v2/compile-jobs", json={})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"
    assert bad.json()["error"]["request_id"]
    for _ in range(100):
        job = client.get(f"/api/v2/compile-jobs/{first.json()['job_id']}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert job["status"] == "completed", job
    assert job["script_id"] == "async_case"
    assert client.get("/api/scripts/async_case/review").status_code == 200
    assert client.post(f"/api/v2/compile-jobs/{job['job_id']}/retry").status_code == 409
    assert client.post("/api/v2/compile-jobs/missing/retry").status_code == 404


def test_v2_eval_job_is_async_and_idempotent(tmp_path, monkeypatch):
    metrics = EvalMetrics(games=4, completed=4, win_rate=0.5, normal_win_rate=0.5,
                          stuck_rate=0, leak_rate=None, mean_turns=10,
                          invariant_failures=0, model_evaluated=False)
    monkeypatch.setattr("jubensha.services.compile_worker.run_eval",
                        lambda *args, **kwargs: SimpleNamespace(run_id="run_1", metrics=metrics))
    client = TestClient(create_app(str(tmp_path / "eval_jobs.db")))
    headers = {"Idempotency-Key": "eval-1"}
    first = client.post("/api/v2/eval-runs", json={"games_per_persona": 1}, headers=headers)
    assert first.status_code == 202
    second = client.post("/api/v2/eval-runs", json={"games_per_persona": 1}, headers=headers)
    assert second.json()["job_id"] == first.json()["job_id"]
    assert client.post("/api/v2/eval-runs", json={"games_per_persona": 2},
                       headers=headers).status_code == 409
    for _ in range(100):
        job = client.get(f"/api/v2/eval-runs/{first.json()['job_id']}").json()
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.02)
    assert job["status"] == "completed", job
    assert job["run_id"] == "run_1" and job["metrics"]["games"] == 4
    assert client.post(f"/api/v2/eval-runs/{job['job_id']}/retry").status_code == 409


def test_v2_delete_draft_removes_uploaded_document(tmp_path, script):
    db_path = tmp_path / "delete.db"
    client = TestClient(create_app(str(db_path)))
    payload = script.model_dump(mode="json") | {"script_id": "delete_case"}
    upload_id = client.post("/api/v2/scripts", data={"authorized": "true", "rights_source": "author original"},
                            files={"file": ("case.json", json.dumps(payload).encode())}).json()["upload_id"]
    compiled = client.post(f"/api/scripts/{upload_id}/compile")
    assert compiled.status_code == 200
    assert client.delete("/api/v2/scripts/delete_case").status_code == 200
    assert client.get("/api/scripts/delete_case/review").status_code == 404
    with EventStore(db_path).connect() as db:
        assert db.execute("SELECT 1 FROM script_uploads WHERE upload_id=?", (upload_id,)).fetchone() is None


def test_v2_game_creation_idempotency(tmp_path):
    client = TestClient(create_app(str(tmp_path / "idempotent.db")))
    headers = {"Idempotency-Key": "new-game-1"}
    first = client.post("/api/v2/games", json={}, headers=headers)
    second = client.post("/api/v2/games", json={}, headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.json()["game_id"] == second.json()["game_id"]
    with EventStore(tmp_path / "idempotent.db").connect() as db:
        assert db.execute("SELECT count(*) FROM games").fetchone()[0] == 1


def test_v2_turn_stream_reconnects_without_replaying_action(tmp_path):
    db_path = tmp_path / "streams.db"
    client = TestClient(create_app(str(db_path)))
    game_id = client.post("/api/v2/games", json={}).json()["game_id"]
    path = f"/api/v2/games/{game_id}/turns?stream=true"
    body = {"action": "begin"}
    assert client.post(path, json=body).status_code == 422
    headers = {"Idempotency-Key": "turn-1"}
    first = client.post(path, json=body, headers=headers)
    assert first.status_code == 200 and "event: done" in first.text
    before = len(EventStore(db_path).events(game_id))
    resumed = client.post(path, json=body,
                          headers=headers | {"Last-Event-ID": "1"})
    assert resumed.status_code == 200 and "event: done" in resumed.text
    assert "id: 1\n" not in resumed.text
    assert len(EventStore(db_path).events(game_id)) == before
    assert client.post(path, json={"action": "read_done"}, headers=headers).status_code == 409
