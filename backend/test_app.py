from copy import deepcopy
from datetime import datetime, timedelta
import sqlite3

import pytest
from fastapi.testclient import TestClient
from backend import app as module
from backend.domain import DEFAULT_TEMPLATE, DEFAULT_SETTINGS, effective_age, forecast, generated_events, event_conflict, suggest_cooling, virgin_clock

NOW = datetime(2026, 9, 9, 14, 0)

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(module, "now_of", lambda db: NOW)
    module.init_db()
    return TestClient(module.app)

def create(client, **kwargs):
    payload = {"purpose": "cross", "female_genotype": "nub-GAL4/CyO", "male_genotype": "UAS-X/TM6B", "setup_date": "2026-09-01", "setup_time": "10:00", **kwargs}
    if payload['purpose'] == 'cross' and 'workflow' not in kwargs:
        payload['workflow'] = {'cross_goal': 'virgins'}
    response = client.post("/api/containers", json=payload)
    assert response.status_code == 200, response.text
    return response.json()

def snapshot(client):
    response = client.get("/api/state")
    assert response.status_code == 200, response.text
    return response.json()

def culture():
    return {"id": "c", "setup_date": "2026-09-01", "setup_time": "10:00", "initial_temperature": 25,
            "template": deepcopy(DEFAULT_TEMPLATE), "status": "active", "parents": "present", "transfer_index": 0, "kind": "vial", "purpose": "cross", "temperature_policy": "allowed"}

def test_d0_and_independent_collection_windows(client):
    c = create(client, setup_date="2026-09-09", setup_time="09:00")
    data = snapshot(client)
    assert data["containers"][0]["calendar_day"] == 0
    events = [e for e in data["events"] if e["container_id"] == c["id"]]
    assert next(e for e in events if e["kind"] == "transfer")["due"] == "2026-09-12T09:00"
    assert len([e for e in events if e["kind"] == "collect"]) == 3
    assert {e["due"][11:] for e in events if e["kind"] == "collect"} == {"09:00", "15:00", "19:00"}

def test_date_only_remains_unknown(client):
    c = create(client, setup_time=None)
    assert c["setup_time"] is None
    assert snapshot(client)["containers"][0]["setup_time"] is None

def test_early_transfer_preserves_source_and_counts(client):
    source = create(client)
    payload = {"purpose": "cross", "female_genotype": source["female_genotype"], "male_genotype": source["male_genotype"], "setup_date": "2026-09-03", "setup_time": "11:00", "mode": "transfer"}
    response = client.post(f"/api/containers/{source['id']}/transfer", json=payload)
    assert response.status_code == 200
    child = response.json()
    assert child["cohort_id"] == source["cohort_id"] and child["transfer_index"] == 1
    data = snapshot(client)
    old = next(c for c in data["containers"] if c["id"] == source["id"])
    assert old["parents"] == "transferred" and old["setup_date"] == "2026-09-01" and old["transfer_index"] == 0
    assert next(e for e in data["events"] if e["container_id"] == child["id"] and e["kind"] == "transfer")["due"] == "2026-09-06T11:00"
    assert next(e for e in data["events"] if e["container_id"] == source["id"] and e["kind"] == "transfer")["status"] == "done"
    assert client.post(f"/api/containers/{source['id']}/transfer", json=payload).status_code == 409
    payload.update(setup_date="2026-09-05")
    last = client.post(f"/api/containers/{child['id']}/transfer", json=payload).json()
    assert last["transfer_index"] == 2
    payload.update(setup_date="2026-09-07")
    assert client.post(f"/api/containers/{last['id']}/transfer", json=payload).status_code == 409

def test_new_generation_resets_cohort(client):
    source = create(client, purpose="stock", genotype="w1118")
    response = client.post(f"/api/containers/{source['id']}/transfer", json={"mode": "generation", "purpose": "stock", "genotype": "w1118", "setup_date": "2026-09-09", "setup_time": "09:00"})
    assert response.status_code == 200
    assert response.json()["transfer_index"] == 0
    assert response.json()["cohort_id"] != source["cohort_id"]

def test_stock_and_bottle_protocol(client):
    stock = create(client, purpose="stock", genotype="w1118", kind="bottle")
    events = [e for e in snapshot(client)["events"] if e["container_id"] == stock["id"]]
    assert any(e["kind"] == "stock" for e in events)
    assert any(e["kind"] == "tissue" for e in events)
    assert not any(e["kind"] == "collect" for e in events)

def test_temperature_changes_development_not_transfer():
    c = culture()
    temps = [{"at": "2026-09-02T10:00", "temperature": 18}, {"at": "2026-09-04T10:00", "temperature": 25}]
    assert effective_age(c, temps, datetime(2026, 9, 4, 10)) == 2
    assert forecast(c, temps, 10) == datetime(2026, 9, 12, 10)
    assert next(e for e in generated_events(c, temps) if e["kind"] == "transfer")["due"] == "2026-09-04T10:00"

def test_completed_and_pinned_events_survive_recalculation(client):
    c = create(client)
    events = snapshot(client)["events"]
    check = next(e for e in events if e["kind"] == "check")
    collect = next(e for e in events if e["kind"] == "collect")
    client.patch(f"/api/events/{check['id']}", json={"status": "done"})
    client.patch(f"/api/events/{collect['id']}", json={"due": "2026-09-20T09:00", "end": "2026-09-20T11:00"})
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "cold", "at": "2026-09-05T10:00"}).status_code == 200
    changed = {e["id"]: e for e in snapshot(client)["events"]}
    assert changed[check["id"]]["status"] == "done"
    assert changed[collect["id"]]["due"] == "2026-09-20T09:00" and changed[collect["id"]]["pinned"]
    assert client.get(f"/api/containers/{c['id']}/suggestions").json()["state"] == "pinned_critical"
    client.patch(f"/api/events/{collect['id']}", json={"restore": True})
    restored = next(e for e in snapshot(client)["events"] if e["id"] == collect["id"])
    assert not restored["pinned"] and restored["due"] != "2026-09-20T09:00"

def test_remove_cancels_only_transfer(client):
    c = create(client)
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "remove", "at": "2026-09-03T10:00"}).status_code == 200
    events = snapshot(client)["events"]
    assert next(e for e in events if e["kind"] == "transfer")["status"] == "cancelled"
    assert all(e["status"] == "pending" for e in events if e["kind"] == "collect")

def test_collection_clock_requires_explicit_clear(client):
    c = create(client)
    client.post(f"/api/containers/{c['id']}/actions", json={"action": "collect", "at": "2026-09-08T20:00"})
    assert snapshot(client)["containers"][0]["clock"]["state"] == "unknown"
    client.post(f"/api/containers/{c['id']}/actions", json={"action": "collect", "at": "2026-09-08T20:00", "cleared": True})
    record = snapshot(client)["containers"][0]
    assert record["clock"]["state"] == "elapsed" and record["parents"] == "removed"
    client.post(f"/api/containers/{c['id']}/actions", json={"action": "cold", "at": "2026-09-08T21:00"})
    assert snapshot(client)["containers"][0]["clock"]["state"] == "mixed"

def test_collection_completion_is_atomic(client):
    c = create(client)
    event = next(e for e in snapshot(client)["events"] if e["kind"] == "collect")
    payload = {"action": "collect", "at": "2026-09-09T13:00", "event_id": event["id"], "cleared": True}
    assert client.post(f"/api/containers/{c['id']}/actions", json=payload).status_code == 200
    before = snapshot(client)
    assert client.post(f"/api/containers/{c['id']}/actions", json=payload).status_code == 409
    after = snapshot(client)
    assert len(before["containers"][0]["logs"]) == len(after["containers"][0]["logs"])

def test_availability_and_partial_slots(client):
    create(client, setup_date="2026-08-30", setup_time="09:00")
    day = "2026-09-09"
    assert client.put('/api/availability', json={"date": day, "kind": "partial", "windows": [["10:00", "12:00"]]}).status_code == 200
    events = [e for e in snapshot(client)["events"] if e["kind"] == "collect" and e["due"].startswith(day)]
    assert len(events) == 3
    assert [e["conflict"] for e in events] == [False, True, True]
    assert client.put('/api/availability', json={"date": day, "kind": "partial", "windows": [["12:00", "09:00"]]}).status_code == 422
    assert client.delete(f'/api/availability/{day}').status_code == 200
    assert not snapshot(client)["availability"]

def test_plan_handles_both_moves_on_workdays():
    c = culture()
    c.update(setup_date="2026-09-02", setup_time="09:00")
    c["template"].update(collection_days=1)
    settings = deepcopy(DEFAULT_SETTINGS)
    now = datetime(2026, 9, 7, 9)
    result = suggest_cooling(c, [], settings, [], now)
    assert result["state"] == "suggested"
    assert result["options"] == sorted(result["options"], key=lambda x: (x["hours"], x["cold_at"]))
    for plan in result["options"]:
        assert datetime.fromisoformat(plan["cold_at"]).weekday() < 5
        assert datetime.fromisoformat(plan["warm_at"]).weekday() < 5
        assert all(not event_conflict(e, settings, []) for e in plan["events"])

def test_forbidden_temperature(client):
    c = create(client, temperature_policy="forbidden")
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "cold", "at": "2026-09-09T10:00"}).status_code == 409
    assert client.get(f"/api/containers/{c['id']}/suggestions").json()["state"] == "forbidden"

def test_no_schedule_solution_when_never_available():
    c = culture()
    settings = deepcopy(DEFAULT_SETTINGS)
    settings["weekly"] = {str(i): [] for i in range(7)}
    assert suggest_cooling(c, [], settings, [], datetime(2026, 9, 2))["state"] == "no_solution"

def test_archive_cancels_and_preserves_history(client):
    c = create(client)
    client.post('/api/events', json={"container_id": c["id"], "title": "Inspect food", "due": "2026-09-10T10:00", "end": "2026-09-10T10:30"})
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "discard", "at": "2026-09-09T10:00"}).status_code == 200
    data = snapshot(client)
    assert data["containers"][0]["status"] == "discarded"
    assert all(e["status"] == "cancelled" for e in data["events"])
    assert client.patch(f"/api/events/{data['events'][0]['id']}", json={"restore": True}).status_code == 409

def test_invalid_time_and_duplicate_label(client):
    c = create(client, label="V01")
    assert client.post('/api/containers', json={"label": "V01", "purpose": "stock", "genotype": "w", "setup_date": "2026-09-01"}).status_code == 409
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "clear", "at": "2026-09-20T10:00"}).status_code == 422
    event = snapshot(client)["events"][0]
    assert client.patch(f"/api/events/{event['id']}", json={"due": "2026-09-10T10:00", "end": "2026-09-09T10:00"}).status_code == 422

def test_future_setup_requires_activation_and_can_start_early(client):
    c = create(client, setup_date="2026-09-11")
    assert c["status"] == "planned"
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "activate", "at": "2026-09-09T10:00"}).status_code == 200
    assert snapshot(client)["containers"][0]["setup_date"] == "2026-09-09"
    assert client.post(f"/api/containers/{c['id']}/actions", json={"action": "activate", "at": "2026-09-09T11:00"}).status_code == 409

def test_backup_contains_committed_data(client, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    c = create(client)
    response = client.get('/api/backup')
    assert response.status_code == 200
    path = tmp_path / 'restored.db'
    path.write_bytes(response.content)
    with sqlite3.connect(path) as restored:
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert restored.execute('SELECT label FROM containers WHERE id=?', (c['id'],)).fetchone()[0] == c['label']

def test_no_cross_origin_mutation(client):
    response = client.post('/api/containers', headers={'Origin': 'https://example.com'}, json={})
    assert response.status_code == 403

def test_settings_are_snapshots_and_windows_are_validated(client):
    c = create(client)
    settings = snapshot(client)["settings"]
    settings["template"]["collection_day"] = 11
    assert client.put('/api/settings', json=settings).status_code == 200
    assert snapshot(client)["containers"][0]["template"]["collection_day"] == 10
    assert create(client)["template"]["collection_day"] == 11
    settings['weekly']['0'] = [['09:00', '12:00'], ['11:00', '15:00']]
    assert client.put('/api/settings', json=settings).status_code == 422

def test_setup_suggestion_does_not_fabricate_actual_setup(client):
    template = {**DEFAULT_TEMPLATE, "collection_days": 1}
    c = create(client, setup_date="2026-09-12", template=template, temperature_policy="forbidden")
    result = client.get(f"/api/containers/{c['id']}/suggestions").json()
    assert result["state"] == "setup_suggested"
    option = result["options"][0]
    assert client.post(f"/api/containers/{c['id']}/setup-plan", json={"setup_at": option["setup_at"]}).status_code == 200
    changed = snapshot(client)["containers"][0]
    assert changed["status"] == "planned"
    assert changed["setup_date"] == option["setup_at"][:10]
    assert not changed["temperatures"]

def test_cooling_plan_creates_tasks_not_temperature_history(client):
    c = create(client, setup_date="2026-09-03", setup_time="09:00", template={**DEFAULT_TEMPLATE, "collection_days": 1})
    result = client.get(f"/api/containers/{c['id']}/suggestions").json()
    assert result["state"] == "suggested"
    option = result["options"][0]
    response = client.post(f"/api/containers/{c['id']}/plans", json={"cold_at": option["cold_at"], "warm_at": option["warm_at"]})
    assert response.status_code == 200, response.text
    data = snapshot(client)
    assert data["containers"][0]["temperature"] == 25
    assert data["containers"][0]["temperatures"] == []
    assert len([e for e in data["events"] if e["kind"] in ("cold", "warm")]) == 2

def test_planned_setup_edit_reforecasts(client):
    c = create(client, setup_date="2026-09-12")
    body = {k: c[k] for k in ("label", "genotype", "female_genotype", "male_genotype", "notes", "temperature_policy", "template")}
    body.update(setup_date="2026-09-14", setup_time="11:00")
    assert client.put(f"/api/containers/{c['id']}", json=body).status_code == 200
    assert next(e for e in snapshot(client)["events"] if e["kind"] == "transfer")["due"] == "2026-09-17T11:00"
    body["setup_time"] = "invalid"
    assert client.put(f"/api/containers/{c['id']}", json=body).status_code == 422
