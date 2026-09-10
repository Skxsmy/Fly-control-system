"""Container-level third-instar collection uses the user's editable D5 preset."""
from datetime import datetime

import pytest

from backend import app as module
from backend.test_workflows import workflow_client, new_culture, state, events_for


def larval_culture(client, **changes):
    return new_culture(client, purpose='larvae', genotype='w1118', **changes)


def edit_body(culture, **changes):
    return {key: culture[key] for key in (
        'label', 'genotype', 'female_genotype', 'male_genotype', 'notes',
        'temperature_policy', 'template', 'workflow',
    )} | changes


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_d0_has_one_d5_collection_with_no_adult_or_d6_tasks(workflow_client, kind):
    client, clock = workflow_client
    culture = larval_culture(client, kind=kind)
    event = events_for(client, culture, 'third_instar', 'pending')
    assert len(event) == 1
    assert event[0]['rule_key'] == 'third_instar' and event[0]['critical']
    assert (event[0]['due'], event[0]['end']) == (
        '2026-09-06T09:00', '2026-09-06T17:00',
    )
    kinds = {item['kind'] for item in events_for(client, culture, status='pending')}
    assert kinds <= {'transfer', 'remove', 'third_instar'}
    assert culture['workflow']['third_instar_day'] == 5
    assert culture['workflow']['third_instar_window'] == ['09:00', '17:00']

    # Simply opening the app after D5 cannot advance the collection or complete it.
    clock['now'] = datetime(2026, 9, 8, 14)
    later = events_for(client, culture, 'third_instar', 'pending')
    assert later == event
    assert datetime.fromisoformat(later[0]['end']) < clock['now']


def test_cross_can_select_f1_larvae_without_adult_scoring_or_virgins(workflow_client):
    client, _ = workflow_client
    culture = new_culture(client, workflow={'cross_goal': 'third_instar'})
    assert culture['female_genotype'] == 'nub-GAL4/CyO'
    assert culture['male_genotype'] == 'UAS-X/TM6B'
    assert not culture['genotype']
    pending = events_for(client, culture, status='pending')
    assert {event['kind'] for event in pending} == {'transfer', 'remove', 'third_instar'}
    assert next(event for event in pending if event['kind'] == 'third_instar')['due'] == '2026-09-06T09:00'


def test_existing_cross_can_switch_to_larvae_without_active_old_adult_tasks(workflow_client):
    client, _ = workflow_client
    culture = new_culture(client, workflow={'cross_goal': 'virgins'})
    old_adult_tasks = events_for(client, culture, 'collect', 'pending')
    response = client.put(f"/api/containers/{culture['id']}", json=edit_body(culture, workflow={
        **culture['workflow'], 'cross_goal': 'third_instar',
    }))
    assert response.status_code == 200, response.text
    pending = events_for(client, culture, status='pending')
    assert {item['kind'] for item in pending} == {'transfer', 'remove', 'third_instar'}
    assert len([item for item in pending if item['kind'] == 'third_instar']) == 1
    after = {item['id']: item for item in events_for(client, culture)}
    assert all(after[item['id']]['status'] == 'cancelled' for item in old_adult_tasks)
    assert (response.json()['setup_date'], response.json()['setup_time']) == (
        culture['setup_date'], culture['setup_time'],
    )


def test_temperature_does_not_silently_scale_the_calendar_day_preset(workflow_client):
    client, clock = workflow_client
    culture = larval_culture(client, initial_temperature=18)
    original = events_for(client, culture, 'third_instar')[0]
    clock['now'] = datetime(2026, 9, 3, 13)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': 'warm', 'at': '2026-09-03T12:00',
    })
    assert response.status_code == 200, response.text
    after = events_for(client, culture, 'third_instar')[0]
    assert (after['id'], after['due'], after['end']) == (
        original['id'], '2026-09-06T09:00', '2026-09-06T17:00',
    )


def test_day_and_collection_window_can_be_changed_without_duplicate_tasks(workflow_client):
    client, _ = workflow_client
    culture = larval_culture(client, workflow={
        'third_instar_day': 4, 'third_instar_window': ['08:15', '10:45'],
    })
    initial = events_for(client, culture, 'third_instar')[0]
    assert (initial['due'], initial['end']) == ('2026-09-05T08:15', '2026-09-05T10:45')
    response = client.put(f"/api/containers/{culture['id']}", json=edit_body(culture, workflow={
        **culture['workflow'], 'third_instar_day': 6,
        'third_instar_window': ['13:00', '14:30'],
    }))
    assert response.status_code == 200, response.text
    after = events_for(client, culture, 'third_instar')
    assert len(after) == 1 and after[0]['id'] == initial['id']
    assert (after[0]['due'], after[0]['end']) == ('2026-09-07T13:00', '2026-09-07T14:30')


@pytest.mark.parametrize('workflow', [
    {'third_instar_day': 0}, {'third_instar_day': 91},
    {'third_instar_window': ['17:00', '09:00']},
    {'third_instar_window': ['25:00', '26:00']},
    {'third_instar_window': ['09:00']},
])
def test_invalid_larval_preset_is_rejected_atomically(workflow_client, workflow):
    client, _ = workflow_client
    before = state(client)
    response = client.post('/api/containers', json={
        'purpose': 'larvae', 'genotype': 'w1118', 'setup_date': '2026-09-01',
        'workflow': workflow,
    })
    assert response.status_code == 422, response.text
    assert state(client) == before


@pytest.mark.parametrize('explicit_event', [False, True])
def test_actual_collection_completes_task_without_claiming_all_larvae_removed(
    workflow_client, explicit_event,
):
    client, clock = workflow_client
    culture = larval_culture(client, stage='larvae')
    event = events_for(client, culture, 'third_instar')[0]
    clock['now'] = datetime(2026, 9, 8, 14)
    payload = {
        'action': 'third_instar', 'at': '2026-09-06T10:25',
        'notes': 'Collected five selected larvae; other animals remain.',
        'cleared': True,  # Adult-clear metadata must never turn a subset harvest into a full removal.
    }
    if explicit_event:
        payload['event_id'] = event['id']
    response = client.post(f"/api/containers/{culture['id']}/actions", json=payload)
    assert response.status_code == 200, response.text
    after = next(item for item in state(client)['containers'] if item['id'] == culture['id'])
    for field in ('setup_date', 'setup_time', 'parents', 'stage', 'status', 'transfer_index'):
        assert after[field] == culture[field]
    recorded = [item for item in after['logs'] if item['action'] == 'third_instar']
    assert len(recorded) == 1
    assert (recorded[0]['at'], recorded[0]['notes']) == (payload['at'], payload['notes'])
    tasks = events_for(client, culture, 'third_instar')
    assert len(tasks) == 1 and tasks[0]['id'] == event['id'] and tasks[0]['status'] == 'done'
    if explicit_event:
        before_retry = state(client)
        assert client.post(f"/api/containers/{culture['id']}/actions", json=payload).status_code == 409
        assert state(client) == before_retry


def test_rescheduling_moves_the_same_task_and_records_actual_collection_time(workflow_client):
    client, clock = workflow_client
    culture = larval_culture(client)
    event = events_for(client, culture, 'third_instar')[0]
    response = client.patch(f"/api/events/{event['id']}", json={
        'due': '2026-09-07T12:00', 'end': '2026-09-07T13:00',
    })
    assert response.status_code == 200, response.text
    for _ in range(2):
        pending = events_for(client, culture, 'third_instar', 'pending')
        assert len(pending) == 1 and pending[0]['id'] == event['id']
        assert pending[0]['due'] == '2026-09-07T12:00' and pending[0]['pinned']
    clock['now'] = datetime(2026, 9, 8, 14)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': 'third_instar', 'at': '2026-09-07T12:20', 'event_id': event['id'],
    })
    assert response.status_code == 200, response.text
    assert not events_for(client, culture, 'third_instar', 'pending')
    assert events_for(client, culture, 'third_instar')[0]['status'] == 'done'


@pytest.mark.parametrize('status', ['skipped', 'disabled'])
def test_manual_skip_or_disable_survives_reconciliation_and_time(workflow_client, status):
    client, clock = workflow_client
    culture = larval_culture(client)
    event = events_for(client, culture, 'third_instar')[0]
    assert client.patch(f"/api/events/{event['id']}", json={'status': status}).status_code == 200
    clock['now'] = datetime(2026, 9, 10, 10)
    remaining = events_for(client, culture, 'third_instar')
    assert len(remaining) == 1 and remaining[0]['id'] == event['id']
    assert remaining[0]['status'] == status


def test_parent_transfer_starts_independent_larval_collection_for_new_tube(workflow_client):
    client, clock = workflow_client
    source = larval_culture(client)
    original = events_for(client, source, 'third_instar')[0]
    clock['now'] = datetime(2026, 9, 3, 13)
    response = client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'transfer', 'purpose': 'larvae', 'genotype': 'w1118',
        'setup_date': '2026-09-03', 'setup_time': '12:00',
    })
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['cohort_id'] == source['cohort_id'] and child['transfer_index'] == 1
    child_events = events_for(client, child, 'third_instar', 'pending')
    assert len(child_events) == 1 and child_events[0]['due'] == '2026-09-08T09:00'
    assert child_events[0]['id'] != original['id']
    after = events_for(client, source, 'third_instar', 'pending')
    assert after == [original]


def test_existing_workflows_do_not_gain_larval_collection(workflow_client):
    client, _ = workflow_client
    stock = new_culture(client, kind='bottle', purpose='stock', genotype='w1118')
    virgin = new_culture(client, purpose='virgin', genotype='w1118')
    scoring = new_culture(client)
    for culture in (stock, virgin, scoring):
        assert not events_for(client, culture, 'third_instar')
    assert {item['kind'] for item in events_for(client, stock)} == {'tissue', 'stock'}
    virgin_events = events_for(client, virgin, 'collect')
    assert len(virgin_events) == 3
    assert {item['due'][:10] for item in virgin_events} == {'2026-09-11'}
    assert len(events_for(client, scoring, 'score')) == 1


def test_legacy_workflow_without_new_fields_reconciles_without_new_larval_tasks(workflow_client):
    client, _ = workflow_client
    culture = new_culture(client)
    initial = events_for(client, culture)
    with module.database() as db:
        stored = module.get_container(db, culture['id'])
        stored['workflow'].pop('third_instar_day', None)
        stored['workflow'].pop('third_instar_window', None)
        module.save_container(db, stored)
    assert events_for(client, culture) == initial
    assert not events_for(client, culture, 'third_instar')


@pytest.mark.parametrize('kind', ['egg_laying', 'petri_dish'])
def test_tube_larval_purpose_is_not_accepted_for_other_container_types(workflow_client, kind):
    client, _ = workflow_client
    response = client.post('/api/containers', json={
        'purpose': 'larvae', 'kind': kind, 'genotype': 'w1118',
        'setup_date': '2026-09-01', 'setup_time': '10:00',
    })
    assert response.status_code == 422, response.text
    assert state(client)['containers'] == []
