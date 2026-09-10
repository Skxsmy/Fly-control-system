"""User-level regressions for distinct purposes and one-day virgin collection."""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest
from fastapi.testclient import TestClient

from backend import app as module


@pytest.fixture
def workflow_client(tmp_path, monkeypatch):
    clock = {"now": datetime(2026, 9, 1, 10)}
    monkeypatch.setattr(module, "DB_PATH", tmp_path / "workflows.db")
    monkeypatch.setattr(module, "now_of", lambda db: clock["now"])
    module.init_db()
    with TestClient(module.app) as client:
        yield client, clock


def new_culture(client, **changes):
    payload = {
        "purpose": "cross",
        "female_genotype": "nub-GAL4/CyO",
        "male_genotype": "UAS-X/TM6B",
        "setup_date": "2026-09-01",
        "setup_time": "10:00",
        **changes,
    }
    response = client.post("/api/containers", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def state(client):
    response = client.get("/api/state")
    assert response.status_code == 200, response.text
    return response.json()


def test_editing_cross_notes_does_not_duplicate_a_pinned_reminder(workflow_client):
    client, _ = workflow_client
    c = new_culture(client)
    event = next(e for e in state(client)['events'] if e['kind'] == 'score')
    client.patch(f"/api/events/{event['id']}", json={'due':'2026-09-12T10:00','end':'2026-09-12T11:00'})
    body = {key:c[key] for key in ('label','genotype','female_genotype','male_genotype','notes','temperature_policy','template')}
    body['workflow'] = {**c['workflow'], 'selection_notes':'Count straight-wing adults'}
    assert client.put(f"/api/containers/{c['id']}", json=body).status_code == 200
    events = [e for e in state(client)['events'] if e['kind'] == 'score']
    assert len(events) == 1 and events[0]['id'] == event['id']
    assert events[0]['pinned'] and events[0]['due'] == '2026-09-12T10:00'


def events_for(client, container, kind=None, status=None):
    return [
        event for event in state(client)["events"]
        if event["container_id"] == container["id"]
        and (kind is None or event["kind"] == kind)
        and (status is None or event["status"] == status)
    ]


def test_new_cross_defaults_to_f1_selection_not_virgin_collection(workflow_client):
    client, _ = workflow_client
    cross = new_culture(client)
    pending = events_for(client, cross, status="pending")

    assert cross["workflow"]["cross_goal"] == "score"
    assert not any(event["kind"] == "collect" for event in pending)
    selection = [event for event in pending if event["kind"] == "score"]
    assert len(selection) == 1
    assert (selection[0]["due"], selection[0]["end"]) == (
        "2026-09-11T09:00", "2026-09-11T17:00"
    )
    assert next(event for event in pending if event["kind"] == "transfer")["due"] == "2026-09-04T10:00"
    removal = next(event for event in pending if event["kind"] == "remove")
    assert (removal["due"], removal["end"]) == ("2026-09-04T09:00", "2026-09-06T17:00")


@pytest.mark.parametrize("options", [
    {"purpose": "virgin", "genotype": "w1118"},
    {"workflow": {"cross_goal": "virgins"}},
])
def test_virgin_collection_has_only_three_windows_on_d10(workflow_client, options):
    client, clock = workflow_client
    culture = new_culture(client, **options)
    initial = events_for(client, culture, "collect", "pending")
    assert [(event["due"], event["end"]) for event in initial] == [
        ("2026-09-11T09:00", "2026-09-11T11:00"),
        ("2026-09-11T15:00", "2026-09-11T15:30"),
        ("2026-09-11T19:00", "2026-09-11T21:00"),
    ]
    assert not events_for(client, culture, "score")

    # Reopening after D10 must not roll the template forward into extra days.
    clock["now"] = datetime(2026, 9, 13, 10)
    after = events_for(client, culture, "collect", "pending")
    assert [(event["id"], event["due"], event["end"]) for event in after] == [
        (event["id"], event["due"], event["end"]) for event in initial
    ]


def test_new_inputs_reject_the_removed_three_day_collection_default(workflow_client):
    client, _ = workflow_client
    response = client.post("/api/containers", json={
        "purpose": "virgin", "genotype": "w1118", "setup_date": "2026-09-01",
        "template": {"collection_days": 3},
    })
    assert response.status_code == 422
    assert state(client)["containers"] == []


def test_stock_maintenance_has_no_parental_cross_or_collection_schedule(workflow_client):
    client, _ = workflow_client
    stock = new_culture(client, purpose="stock", genotype="w1118", kind="bottle")
    pending = events_for(client, stock, status="pending")
    assert stock["workflow"]["transfer_enabled"] is False
    assert {event["kind"] for event in pending} == {"tissue", "stock"}
    assert next(event for event in pending if event["kind"] == "stock")["due"] == "2026-09-12T09:00"


def test_egg_and_dish_workflows_do_not_inherit_f1_or_virgin_tasks(workflow_client):
    client, clock = workflow_client
    cage = new_culture(client, purpose="egg_laying", kind="egg_laying", genotype="w1118")
    assert events_for(client, cage) == []
    clock["now"] = datetime(2026, 9, 1, 15)
    dish = new_culture(client, purpose="dissection", kind="petri_dish", genotype="w1118",
        setup_time="14:00", incubation={
            "lay_start": "2026-09-01T10:00", "lay_end": "2026-09-01T12:00",
            "min_hours": 24, "max_hours": 30,
        })
    pending = events_for(client, dish, status="pending")
    assert len(pending) == 1 and pending[0]["kind"] == "first_instar"
    assert (pending[0]["due"], pending[0]["end"]) == (
        "2026-09-02T10:00", "2026-09-02T18:00"
    )


@pytest.mark.parametrize("goal,follow,expected_day", [
    ("score", True, "2026-09-13"),
    ("score", False, "2026-09-11"),
    ("virgins", True, "2026-09-11"),
])
def test_observed_eclosion_can_anchor_f1_scoring_but_never_moves_virgin_day(
    workflow_client, goal, follow, expected_day
):
    client, clock = workflow_client
    culture = new_culture(client, workflow={"cross_goal": goal, "follow_eclosion": follow})
    kind = "score" if goal == "score" else "collect"
    before = events_for(client, culture, kind, "pending")
    clock["now"] = datetime(2026, 9, 13, 14)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        "action": "eclosion", "at": "2026-09-13T10:00", "notes": "First F1 adults observed",
    })
    assert response.status_code == 200, response.text
    assert response.json()["first_eclosion_at"] == "2026-09-13T10:00"
    after = events_for(client, culture, kind, "pending")
    assert {event["id"] for event in after} == {event["id"] for event in before}
    assert {event["due"][:10] for event in after} == {expected_day}
    assert len(after) == (1 if goal == "score" else 3)


def test_migration_cancels_extra_automatic_days_without_replacing_event_history(workflow_client):
    client, _ = workflow_client
    culture = new_culture(client, workflow={"cross_goal": "virgins"})
    first_day = events_for(client, culture, "collect")
    legacy_events = deepcopy(first_day)
    for offset in (1, 2):
        for slot, first in enumerate(first_day):
            event = deepcopy(first)
            event.update(id=f"legacy-extra-{offset}-{slot}", rule_key=first["rule_key"].replace("collect-0-", f"collect-{offset}-"))
            event["due"] = (datetime.fromisoformat(first["due"]) + timedelta(days=offset)).isoformat(timespec="minutes")
            event["end"] = (datetime.fromisoformat(first["end"]) + timedelta(days=offset)).isoformat(timespec="minutes")
            if offset == 2 and slot == 0:
                event.update(status="done", title="Recorded collection retained from previous version")
            legacy_events.append(event)
    with module.database() as db:
        stored = module.get_container(db, culture["id"])
        stored.pop("workflow")
        stored["template"]["collection_days"] = 3
        module.save_container(db, stored)
        for event in legacy_events:
            module.save_event(db, event)
        settings = module.settings_of(db)
        settings["template"]["collection_days"] = 3
        db.execute("UPDATE meta SET value=? WHERE key='settings'", (json.dumps(settings),))
        db.execute("DELETE FROM meta WHERE key='single_day_collection_v1'")

    module.init_db()
    migrated = state(client)
    assert migrated["settings"]["template"]["collection_days"] == 1
    stored = next(item for item in migrated["containers"] if item["id"] == culture["id"])
    assert stored["template"]["collection_days"] == 1
    assert "workflow" not in stored  # Existing cross intent is retained.
    after = events_for(client, culture, "collect")
    assert {event["id"] for event in after} == {event["id"] for event in legacy_events}
    assert len([event for event in after if event["status"] == "pending"]) == 3
    assert len([event for event in after if event["status"] == "cancelled"]) == 5
    history = next(event for event in after if event["id"] == "legacy-extra-2-0")
    assert (history["status"], history["due"], history["title"]) == (
        "done", "2026-09-13T09:00", "Recorded collection retained from previous version"
    )
    assert {event["due"][:10] for event in after if event["status"] == "pending"} == {"2026-09-11"}

    # Migration and repeated reconciliation cannot resurrect D11/D12 or allocate new IDs.
    module.init_db()
    assert events_for(client, culture, "collect") == after


def test_explicit_cross_outcome_change_preserves_pinned_and_custom_work(workflow_client):
    client, _ = workflow_client
    culture = new_culture(client, workflow={"cross_goal": "virgins"})
    automatic = events_for(client, culture, "collect", "pending")
    pinned = automatic[0]
    response = client.patch(f"/api/events/{pinned['id']}", json={
        "due": "2026-09-14T10:00", "end": "2026-09-14T11:00",
    })
    assert response.status_code == 200, response.text
    response = client.post("/api/events", json={
        "container_id": culture["id"], "title": "Photograph selected F1 wings",
        "due": "2026-09-15T14:00", "end": "2026-09-15T15:00",
    })
    assert response.status_code == 200, response.text
    custom = response.json()
    payload = {key: culture[key] for key in (
        "label", "genotype", "female_genotype", "male_genotype", "notes", "temperature_policy", "template"
    )}
    payload["workflow"] = {**culture["workflow"], "cross_goal": "score"}
    response = client.put(f"/api/containers/{culture['id']}", json=payload)
    assert response.status_code == 200, response.text
    after = {event["id"]: event for event in events_for(client, culture)}
    assert after[pinned["id"]]["status"] == "pending"
    assert after[pinned["id"]]["rule_key"].startswith("custom-preserved-")
    assert after[pinned["id"]]["pinned"] is True
    assert (after[pinned["id"]]["due"], after[pinned["id"]]["end"]) == (
        "2026-09-14T10:00", "2026-09-14T11:00"
    )
    assert after[custom["id"]]["status"] == "pending"
    assert after[custom["id"]]["title"] == "Photograph selected F1 wings"
    assert all(after[event["id"]]["status"] == "cancelled" for event in automatic[1:])
    assert len(events_for(client, culture, "score", "pending")) == 1


def test_early_parent_removal_completes_removal_and_keeps_original_d0(workflow_client):
    client, clock = workflow_client
    culture = new_culture(client)
    scoring = events_for(client, culture, "score", "pending")[0]
    clock["now"] = datetime(2026, 9, 3, 13)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        "action": "remove", "at": "2026-09-03T12:00", "notes": "Parents removed on D2",
    })
    assert response.status_code == 200, response.text
    assert response.json()["parents"] == "removed"
    assert (response.json()["setup_date"], response.json()["setup_time"]) == ("2026-09-01", "10:00")
    assert events_for(client, culture, "transfer")[0]["status"] == "cancelled"
    assert events_for(client, culture, "remove")[0]["status"] == "done"
    after = events_for(client, culture, "score", "pending")[0]
    assert (after["id"], after["due"], after["end"]) == (scoring["id"], scoring["due"], scoring["end"])
    # Recording the same physical removal twice cannot add another operation.
    assert client.post(f"/api/containers/{culture['id']}/actions", json={
        "action": "remove", "at": "2026-09-03T12:30",
    }).status_code == 409
    logs = next(item for item in state(client)["containers"] if item["id"] == culture["id"])["logs"]
    assert len([item for item in logs if item["action"] == "remove"]) == 1
