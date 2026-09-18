"""Independent API acceptance checks for the researcher's injection preparation flow.

Every case uses the isolated workflow fixture and a simulated laboratory clock.
These checks follow user operations rather than calling workflow internals.
"""
from datetime import datetime

import pytest

from backend.test_workflows import events_for, new_culture, state, workflow_client


def set_now(clock, stamp):
    clock["now"] = datetime.fromisoformat(stamp)


def current(client, culture):
    return next(c for c in state(client)["containers"] if c["id"] == culture["id"])


def children(client, culture):
    return [c for c in state(client)["containers"] if c.get("source_id") == culture["id"]]


def start_preparation(client, source, at="2026-09-01T10:00"):
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        "at": at, "genotype": "w1118", "notes": "Preparation for planned injections",
    })
    assert response.status_code == 200, response.text
    linked = children(client, source)
    assert len(linked) == 1
    return linked[0]


def operate(client, owner, action, at, **fields):
    response = client.post(f"/api/containers/{owner['id']}/injection-actions", json={
        "action": action, "at": at, **fields,
    })
    assert response.status_code == 200, response.text
    return response.json()


def collect(client, source, at, **fields):
    return operate(client, source, "injection_collect", at,
                   female_count=200, male_count=60, **fields)


def sole_pending(client, owner, kind):
    pending = events_for(client, owner, kind, "pending")
    assert len(pending) == 1, pending
    return pending[0]


def active_cage(client, clock, kind="vial"):
    source = new_culture(client, kind=kind, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, "2026-09-11T10:00")
    collect(client, source, "2026-09-11T10:00")
    set_now(clock, "2026-09-15T10:00")
    cage = children(client, bottle)[0]
    transfer = sole_pending(client, bottle, "injection_transfer")
    operate(client, bottle, "injection_transfer", "2026-09-15T10:00", event_id=transfer["id"])
    return source, bottle, current(client, cage)


@pytest.mark.parametrize("kind", ["vial", "bottle"])
def test_complete_chain_uses_actual_anchors_and_continuation_immediately_renews(workflow_client, kind):
    client, clock = workflow_client
    source = new_culture(client, kind=kind, purpose="stock", genotype="w1118")
    renewal = sole_pending(client, source, "stock")
    # Starting preparation must cancel even an explicitly rescheduled stock task.
    pinned = client.patch(f"/api/events/{renewal['id']}", json={
        "due": "2026-09-15T09:00", "end": "2026-09-15T17:00",
    })
    assert pinned.status_code == 200, pinned.text
    bottle = start_preparation(client, source)
    assert bottle["kind"] == "bottle" and bottle["purpose"] == "injection"
    assert bottle["label"].startswith("IB")
    assert bottle["status"] == "planned"
    assert bottle["injection"]["started_at"] is None
    assert not events_for(client, source, "stock", "pending")
    cancelled_renewal = next(e for e in state(client)["events"] if e["id"] == renewal["id"])
    assert cancelled_renewal["status"] == "cancelled"
    collection = events_for(client, source, "injection_collect", "pending")
    assert [(e["due"], e["end"]) for e in collection] == [
        ("2026-09-11T00:00", "2026-09-11T23:59"),
        ("2026-09-12T00:00", "2026-09-12T23:59"),
        ("2026-09-13T00:00", "2026-09-13T23:59"),
    ]
    assert all(e.get("all_day") is True for e in collection)
    assert not children(client, bottle)

    set_now(clock, "2026-09-11T09:17")
    collect(client, source, "2026-09-11T09:17", event_id=collection[0]["id"])
    bottle = current(client, bottle)
    assert (bottle["setup_date"], bottle["setup_time"]) == ("2026-09-11", "09:17")
    assert bottle["injection"]["started_at"] == "2026-09-11T09:17"
    assert bottle["status"] == "active" and bottle["genotype"] == "w1118"
    assert not events_for(client, source, "injection_collect", "pending")
    collection_after = events_for(client, source, "injection_collect")
    assert {e["id"] for e in collection_after} == {e["id"] for e in collection}
    assert [e["status"] for e in collection_after].count("done") == 1
    assert [e["status"] for e in collection_after].count("cancelled") == 2
    transfer = sole_pending(client, bottle, "injection_transfer")
    assert transfer["due"] == "2026-09-15T09:17"

    set_now(clock, "2026-09-15T09:16")
    assert children(client, bottle) == []
    set_now(clock, "2026-09-15T09:17")
    cage = children(client, bottle)[0]
    assert cage["kind"] == "cage" and cage["label"].startswith("C")
    assert cage["status"] == "planned"
    assert cage["injection"].get("transferred_at") is None
    assert (cage["setup_date"], cage["setup_time"]) == ("2026-09-11", "09:17")
    assert current(client, bottle)["status"] == "active"
    # Time passing only materializes a plan; it never records a transfer.
    assert not [log for log in current(client, bottle)["logs"] if log["action"] == "injection_transfer"]
    assert [c["id"] for c in children(client, bottle)] == [cage["id"]]

    set_now(clock, "2026-09-16T12:00")
    operate(client, bottle, "injection_transfer", "2026-09-16T10:30", event_id=transfer["id"])
    assert current(client, bottle)["status"] == "discarded"
    assert current(client, cage)["status"] == "active"
    # A late physical transfer must not reset the inherited conditioning clock.
    renewal = sole_pending(client, cage, "injection_renew")
    assert renewal["due"] == "2026-09-16T09:17"
    operate(client, cage, "injection_renew", "2026-09-16T12:00", event_id=renewal["id"])
    embryos = sole_pending(client, cage, "injection_embryos")
    assert embryos["due"] == "2026-09-16T12:30"

    set_now(clock, "2026-09-16T12:35")
    operate(client, cage, "injection_embryos", "2026-09-16T12:35",
            event_id=embryos["id"], continue_collection=True)
    following = sole_pending(client, cage, "injection_embryos")
    assert following["id"] != embryos["id"] and following["due"] == "2026-09-16T13:05"
    assert not events_for(client, cage, "injection_renew", "pending")
    assert current(client, cage)["injection"]["renewed_at"] == "2026-09-16T12:35"

    set_now(clock, "2026-09-16T13:10")
    operate(client, cage, "injection_embryos", "2026-09-16T13:10",
            event_id=following["id"], continue_collection=False)
    assert current(client, cage)["status"] == "active"
    assert current(client, cage)["injection"]["phase"] == "finished"
    assert not events_for(client, cage, status="pending")
    assert len(children(client, bottle)) == 1


@pytest.mark.parametrize("completion", ["2026-09-10T08:35", "2026-09-14T16:41"])
def test_collection_can_be_recorded_early_or_late_without_inventing_an_anchor(workflow_client, completion):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, completion)
    collect(client, source, completion)
    assert current(client, bottle)["injection"]["started_at"] == completion
    assert not events_for(client, source, "injection_collect", "pending")


def test_awaiting_flies_remains_planned_despite_time_passing(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, "2026-10-15T12:00")
    for _ in range(3):
        assert current(client, bottle)["status"] == "planned"
        assert current(client, bottle)["injection"]["started_at"] is None
        assert children(client, bottle) == []
        assert not events_for(client, bottle, status="pending")


@pytest.mark.parametrize("kind", ["vial", "bottle"])
def test_collection_predictions_reuse_full_partial_day_temperature_history(workflow_client, kind):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118", kind=kind)
    history = [
        ("cold", "2026-09-03T16:30"),
        ("warm", "2026-09-05T08:15"),
        ("cold", "2026-09-06T12:45"),
        ("warm", "2026-09-08T14:15"),
    ]
    for action, at in history:
        set_now(clock, at)
        response = client.post(f"/api/containers/{source['id']}/actions", json={"action": action, "at": at})
        assert response.status_code == 200, response.text
    temperatures_before = current(client, source)["temperatures"]
    start_preparation(client, source, "2026-09-08T14:15")
    original = events_for(client, source, "injection_collect", "pending")
    # 39 h 45 min and 49 h 30 min cold intervals retain a combined 44 h
    # 37 min 30 sec developmental delay, even though preparation is at 25°C.
    assert [e["due"][:10] for e in original] == ["2026-09-13", "2026-09-14", "2026-09-15"]
    assert all(e["due"].endswith("T00:00") and e["end"].endswith("T23:59") for e in original)
    assert current(client, source)["temperatures"] == temperatures_before
    assert current(client, source)["temperature_policy"] == "forbidden"

    set_now(clock, "2026-09-09T14:15")
    rejected = client.post(f"/api/containers/{source['id']}/actions", json={
        "action": "cold", "at": "2026-09-09T14:15",
    })
    assert rejected.status_code == 409, rejected.text
    stored = current(client, source)
    edit = {key: stored[key] for key in (
        "label", "genotype", "female_genotype", "male_genotype", "notes", "temperature_policy", "template",
    )}
    edit["temperature_policy"] = "allowed"
    rejected = client.put(f"/api/containers/{source['id']}", json=edit)
    assert rejected.status_code == 409, rejected.text
    after = events_for(client, source, "injection_collect", "pending")
    assert [(e["id"], e["due"], e["end"]) for e in after] == [(e["id"], e["due"], e["end"]) for e in original]
    assert current(client, source)["temperatures"] == temperatures_before


@pytest.mark.parametrize("kind", ["vial", "bottle"])
@pytest.mark.parametrize("initial_cold", [False, True])
def test_currently_cold_source_requires_recorded_warming_before_preparation(workflow_client, kind, initial_cold):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118", kind=kind,
                         initial_temperature=18 if initial_cold else 25)
    if not initial_cold:
        set_now(clock, "2026-09-02T10:00")
        response = client.post(f"/api/containers/{source['id']}/actions", json={
            "action": "cold", "at": "2026-09-02T10:00",
        })
        assert response.status_code == 200, response.text
    set_now(clock, "2026-09-04T10:00")
    before = current(client, source)
    rejected = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        "at": "2026-09-04T10:00", "genotype": "w1118",
    })
    assert rejected.status_code == 409, rejected.text
    after = current(client, source)
    assert not after.get("injection")
    assert after["temperature"] == 18
    assert after["temperatures"] == before["temperatures"]
    assert after["logs"] == before["logs"]
    assert children(client, source) == []
    assert not events_for(client, source, "injection_collect")
    assert sole_pending(client, source, "stock")

    warmed = client.post(f"/api/containers/{source['id']}/actions", json={
        "action": "warm", "at": "2026-09-04T10:00",
    })
    assert warmed.status_code == 200, warmed.text
    bottle = start_preparation(client, source, "2026-09-04T10:00")
    assert bottle["status"] == "planned"
    assert current(client, source)["temperature"] == 25
    assert current(client, source)["temperature_policy"] == "forbidden"
    assert len(events_for(client, source, "injection_collect", "pending")) == 3


def test_backdated_preparation_cannot_straddle_a_recorded_cold_interval(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    for action, at in (("cold", "2026-09-02T10:00"), ("warm", "2026-09-03T10:00")):
        set_now(clock, at)
        recorded = client.post(f"/api/containers/{source['id']}/actions", json={"action": action, "at": at})
        assert recorded.status_code == 200, recorded.text
    rejected = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        "at": "2026-09-01T10:00", "genotype": "w1118",
    })
    # Both endpoints are at 25°C, but the proposed preparation interval includes
    # a real 18°C stay. Correct the entry time instead of hiding that history.
    assert rejected.status_code == 422, rejected.text
    assert not current(client, source).get("injection")
    assert children(client, source) == []


def test_preparation_cancels_previously_accepted_temperature_plan_without_recording_moves(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, kind="bottle", purpose="larvae", genotype="w1118",
                         setup_time="09:00", parents="removed",
                         workflow={"cross_goal": "third_instar", "transfer_enabled": False})
    set_now(clock, "2026-09-03T09:00")
    suggested = client.get(f"/api/containers/{source['id']}/suggestions")
    assert suggested.status_code == 200 and suggested.json()["state"] == "suggested", suggested.text
    option = suggested.json()["options"][0]
    accepted = client.post(f"/api/containers/{source['id']}/plans", json={
        "cold_at": option["cold_at"], "warm_at": option["warm_at"],
    })
    assert accepted.status_code == 200, accepted.text
    plan_events = [e for e in events_for(client, source, status="pending") if e["rule_key"].startswith("plan-")]
    assert {e["kind"] for e in plan_events} == {"cold", "warm"}
    custom = client.post("/api/events", json={
        "container_id": source["id"], "title": "Check injection equipment",
        "due": "2026-09-04T10:00", "end": "2026-09-04T11:00",
    })
    assert custom.status_code == 200, custom.text
    start_preparation(client, source, "2026-09-03T09:00")
    after = state(client)
    for planned in plan_events:
        assert next(e for e in after["events"] if e["id"] == planned["id"])["status"] == "cancelled"
    assert next(e for e in after["events"] if e["id"] == custom.json()["id"])["status"] == "pending"
    assert current(client, source)["temperatures"] == []
    assert current(client, source)["temperature"] == 25
    assert any(p["id"] == accepted.json()["id"] for p in after["plans"])


@pytest.mark.parametrize("stamp", ["2026-08-31T10:00", "2026-09-02T10:00"])
def test_preparation_rejects_before_source_and_future_actual_dates(workflow_client, stamp):
    client, _ = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={"at": stamp, "genotype": "w1118"})
    assert response.status_code == 422, response.text
    assert children(client, source) == []
    assert sole_pending(client, source, "stock")


@pytest.mark.parametrize("stamp", ["2026-09-01T10:00", "2026-09-12T10:00"])
def test_collection_rejects_before_preparation_and_future_actual_dates(workflow_client, stamp):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    set_now(clock, "2026-09-02T10:00")
    bottle = start_preparation(client, source, "2026-09-02T10:00")
    set_now(clock, "2026-09-11T10:00")
    response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
        "action": "injection_collect", "at": stamp, "female_count": 200, "male_count": 60,
    })
    assert response.status_code == 422, response.text
    assert current(client, bottle)["status"] == "planned"


@pytest.mark.parametrize("female,male", [(-1, 50), (200, -1), (200.5, 50), (200, 50.5)])
def test_counts_must_be_nonnegative_whole_flies(workflow_client, female, male):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, "2026-09-11T10:00")
    response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
        "action": "injection_collect", "at": "2026-09-11T10:00", "female_count": female, "male_count": male,
    })
    assert response.status_code == 422, response.text
    assert current(client, bottle)["status"] == "planned"


def test_researcher_can_confirm_recorded_counts_below_target(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, "2026-09-11T10:00")
    operate(client, source, "injection_collect", "2026-09-11T10:00", female_count=180, male_count=55)
    assert current(client, bottle)["status"] == "active"
    assert current(client, bottle)["injection"]["female_count"] == 180
    assert current(client, bottle)["injection"]["male_count"] == 55


def test_managed_tasks_cannot_be_completed_by_generic_event_patch(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    collection = events_for(client, source, "injection_collect", "pending")[0]
    rejected = client.patch(f"/api/events/{collection['id']}", json={"status": "done"})
    assert rejected.status_code == 409, rejected.text
    assert current(client, bottle)["status"] == "planned"
    set_now(clock, "2026-09-11T10:00")
    collect(client, source, "2026-09-11T10:00")
    transfer = sole_pending(client, bottle, "injection_transfer")
    rejected = client.patch(f"/api/events/{transfer['id']}", json={"status": "done"})
    assert rejected.status_code == 409, rejected.text
    assert current(client, bottle)["status"] == "active"


def test_repeated_actions_do_not_create_duplicate_children_or_cycles(workflow_client):
    client, clock = workflow_client
    source, bottle, cage = active_cage(client, clock)
    rejected = client.post(f"/api/containers/{source['id']}/injection-actions", json={
        "action": "injection_collect", "at": "2026-09-11T10:00", "female_count": 200, "male_count": 60,
    })
    assert rejected.status_code == 409, rejected.text
    assert len(children(client, source)) == len(children(client, bottle)) == 1
    set_now(clock, "2026-09-16T10:00")
    renewal = sole_pending(client, cage, "injection_renew")
    operate(client, cage, "injection_renew", "2026-09-16T10:00", event_id=renewal["id"])
    embryos = sole_pending(client, cage, "injection_embryos")
    set_now(clock, "2026-09-16T10:30")
    payload = {"action": "injection_embryos", "at": "2026-09-16T10:30", "event_id": embryos["id"], "continue_collection": True}
    assert client.post(f"/api/containers/{cage['id']}/injection-actions", json=payload).status_code == 200
    following = sole_pending(client, cage, "injection_embryos")
    rejected = client.post(f"/api/containers/{cage['id']}/injection-actions", json=payload)
    assert rejected.status_code == 409, rejected.text
    assert sole_pending(client, cage, "injection_embryos")["id"] == following["id"]


@pytest.mark.parametrize("action", ["activate", "cold", "warm"])
def test_planned_conditioning_bottle_requires_the_workflow_operation(workflow_client, action):
    client, _ = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    rejected = client.post(f"/api/containers/{bottle['id']}/actions", json={"action": action, "at": "2026-09-01T10:00"})
    assert rejected.status_code in (409, 422), rejected.text
    assert current(client, bottle)["status"] == "planned"


def test_cycle_confirmation_rejects_before_renewal_and_future_times(workflow_client):
    client, clock = workflow_client
    _, _, cage = active_cage(client, clock)
    set_now(clock, "2026-09-16T12:00")
    renewal = sole_pending(client, cage, "injection_renew")
    operate(client, cage, "injection_renew", "2026-09-16T12:00", event_id=renewal["id"])
    embryos = sole_pending(client, cage, "injection_embryos")
    for at in ("2026-09-16T11:59", "2026-09-16T12:30"):
        rejected = client.post(f"/api/containers/{cage['id']}/injection-actions", json={
            "action": "injection_embryos", "at": at, "event_id": embryos["id"], "continue_collection": True,
        })
        assert rejected.status_code == 422, rejected.text
        assert sole_pending(client, cage, "injection_embryos")["id"] == embryos["id"]


def test_injection_bottle_numbers_are_independent_of_ordinary_bottles(workflow_client):
    client, _ = workflow_client
    ordinary = new_culture(client, kind="bottle", purpose="stock", genotype="w1118")
    source = new_culture(client, kind="vial", purpose="stock", genotype="w1118")
    preparation = start_preparation(client, source)
    another_ordinary = new_culture(client, kind="bottle", purpose="stock", genotype="w1118")
    second_preparation = start_preparation(client, ordinary)
    assert [ordinary["label"], another_ordinary["label"]] == ["B0001", "B0002"]
    assert [preparation["label"], second_preparation["label"]] == ["IB0001", "IB0002"]


def test_known_collected_genotype_does_not_overwrite_cross_parents(workflow_client):
    client, _ = workflow_client
    source = new_culture(client)
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        "at": "2026-09-01T10:00", "genotype": "nub-GAL4/+; UAS-X/+",
    })
    assert response.status_code == 200, response.text
    assert children(client, source)[0]["genotype"] == "nub-GAL4/+; UAS-X/+"
    preserved = current(client, source)
    assert (preserved["female_genotype"], preserved["male_genotype"]) == (
        source["female_genotype"], source["male_genotype"],
    )
    assert preserved["genotype"] == source["genotype"]


def test_manual_early_transfer_creates_cage_and_preserves_original_day_zero(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose="stock", genotype="w1118")
    bottle = start_preparation(client, source)
    set_now(clock, "2026-09-11T08:15")
    collect(client, source, "2026-09-11T08:15")
    set_now(clock, "2026-09-13T14:35")
    assert children(client, bottle) == []
    operate(client, bottle, "injection_transfer", "2026-09-13T14:35")
    cage = children(client, bottle)[0]
    assert cage["status"] == "active" and cage["injection"]["transferred_at"] == "2026-09-13T14:35"
    assert datetime.fromisoformat(cage["injection"]["started_at"]) == datetime(2026, 9, 11, 8, 15)
    assert sole_pending(client, cage, "injection_renew")["due"] == "2026-09-16T08:15"
    assert current(client, bottle)["status"] == "discarded"


def test_late_cycle_restarts_thirty_minutes_from_actual_collection_not_old_due(workflow_client):
    client, clock = workflow_client
    _, _, cage = active_cage(client, clock)
    set_now(clock, "2026-09-16T10:00")
    renewal = sole_pending(client, cage, "injection_renew")
    operate(client, cage, "injection_renew", "2026-09-16T10:00", event_id=renewal["id"])
    embryos = sole_pending(client, cage, "injection_embryos")
    assert embryos["due"] == "2026-09-16T10:30"
    set_now(clock, "2026-09-17T15:10")
    operate(client, cage, "injection_embryos", "2026-09-17T15:10",
            event_id=embryos["id"], continue_collection=True)
    assert sole_pending(client, cage, "injection_embryos")["due"] == "2026-09-17T15:40"


@pytest.mark.parametrize("incomplete", ["missing_count", "missing_continue", "missing_event"])
def test_incomplete_confirmation_does_not_partially_advance_the_workflow(workflow_client, incomplete):
    client, clock = workflow_client
    if incomplete == "missing_count":
        source = new_culture(client, purpose="stock", genotype="w1118")
        bottle = start_preparation(client, source)
        set_now(clock, "2026-09-11T10:00")
        rejected = client.post(f"/api/containers/{source['id']}/injection-actions", json={
            "action": "injection_collect", "at": "2026-09-11T10:00", "female_count": 200,
        })
        assert rejected.status_code == 422, rejected.text
        assert current(client, bottle)["status"] == "planned"
        assert len(events_for(client, source, "injection_collect", "pending")) == 3
        return
    _, _, cage = active_cage(client, clock)
    set_now(clock, "2026-09-16T10:00")
    renewal = sole_pending(client, cage, "injection_renew")
    if incomplete == "missing_event":
        rejected = client.post(f"/api/containers/{cage['id']}/injection-actions", json={
            "action": "injection_renew", "at": "2026-09-16T10:00",
        })
        assert rejected.status_code == 422, rejected.text
        assert sole_pending(client, cage, "injection_renew")["id"] == renewal["id"]
        assert events_for(client, cage, "injection_embryos") == []
        return
    operate(client, cage, "injection_renew", "2026-09-16T10:00", event_id=renewal["id"])
    embryos = sole_pending(client, cage, "injection_embryos")
    set_now(clock, "2026-09-16T10:30")
    rejected = client.post(f"/api/containers/{cage['id']}/injection-actions", json={
        "action": "injection_embryos", "at": "2026-09-16T10:30", "event_id": embryos["id"],
    })
    assert rejected.status_code == 422, rejected.text
    assert sole_pending(client, cage, "injection_embryos")["id"] == embryos["id"]
