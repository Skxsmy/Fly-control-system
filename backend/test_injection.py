"""State-machine boundaries for the researcher-defined preparation workflow."""
from datetime import datetime

import pytest

from backend.test_workflows import workflow_client, new_culture, state


def start(client, **kwargs):
    source = new_culture(client, purpose='stock', genotype='w1118', **kwargs)
    response = client.post(f'/api/containers/{source["id"]}/injection-preparation',
                           json={'at': '2026-09-01T10:00', 'genotype': 'w1118'})
    assert response.status_code == 200, response.text
    return response.json()['source'], response.json()['bottle']


def do(client, c, action, at, **kwargs):
    return client.post(f'/api/containers/{c["id"]}/injection-actions', json={'action': action, 'at': at, **kwargs})


def cage_ready(client, clock):
    source, bottle = start(client)
    clock['now'] = datetime(2026, 9, 11, 10)
    assert do(client, source, 'injection_collect', '2026-09-11T10:00', female_count=200, male_count=50).status_code == 200
    clock['now'] = datetime(2026, 9, 15, 10)
    response = do(client, bottle, 'injection_transfer', '2026-09-15T10:00')
    assert response.status_code == 200, response.text
    return source, bottle, response.json()['cage']


def pending(client, cid, kind):
    return next(e for e in state(client)['events'] if e['container_id'] == cid and e['kind'] == kind and e['status'] == 'pending')


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_cancels_pinned_renewal_and_keeps_existing_event_history(workflow_client, kind):
    client, clock = workflow_client
    source = new_culture(client, kind=kind, purpose='stock', genotype='w1118')
    renewal = pending(client, source['id'], 'stock')
    assert client.patch(f'/api/events/{renewal["id"]}', json={'due': '2026-09-13T12:00'}).status_code == 200
    assert client.post(f'/api/containers/{source["id"]}/injection-preparation',
                       json={'at': '2026-09-01T10:00', 'genotype': 'w1118'}).status_code == 200
    snapshot = state(client)
    old = next(e for e in snapshot['events'] if e['id'] == renewal['id'])
    assert old['status'] == 'cancelled' and old['pinned']
    assert not any(e['kind'] == 'stock' and e['status'] == 'pending' for e in snapshot['events'])


@pytest.mark.parametrize('counts', [{}, {'female_count': 1.5, 'male_count': 50}, {'female_count': True, 'male_count': 50}, {'female_count': -1, 'male_count': 50}])
def test_invalid_actual_counts_rollback(workflow_client, counts):
    client, clock = workflow_client
    source, bottle = start(client)
    clock['now'] = datetime(2026, 9, 11, 10)
    before = state(client)
    assert do(client, source, 'injection_collect', '2026-09-11T10:00', **counts).status_code == 422
    assert state(client) == before


def test_below_target_counts_are_researcher_confirmation_not_blocker(workflow_client):
    client, clock = workflow_client
    source, bottle = start(client)
    clock['now'] = datetime(2026, 9, 11, 10)
    response = do(client, source, 'injection_collect', '2026-09-11T09:30', female_count=80, male_count=30)
    assert response.status_code == 200, response.text
    actual = response.json()['bottle']
    assert actual['setup_time'] == '09:30'
    assert actual['injection']['female_count'] == 80
    assert actual['injection']['male_count'] == 30


def test_replayed_cycle_cannot_collect_again_after_reopening_old_reminder(workflow_client):
    client, clock = workflow_client
    _, _, cage = cage_ready(client, clock)
    clock['now'] = datetime(2026, 9, 16, 10)
    event = pending(client, cage['id'], 'injection_renew')
    assert do(client, cage, 'injection_renew', '2026-09-16T10:00', event_id=event['id']).status_code == 200
    event = pending(client, cage['id'], 'injection_embryos')
    clock['now'] = datetime(2026, 9, 16, 10, 30)
    assert do(client, cage, 'injection_embryos', '2026-09-16T10:30', event_id=event['id'], continue_collection=True).status_code == 200
    assert client.patch(f'/api/events/{event["id"]}', json={'status': 'pending'}).status_code == 200
    replay = do(client, cage, 'injection_embryos', '2026-09-16T10:30', event_id=event['id'], continue_collection=True)
    assert replay.status_code == 409
    newer = pending(client, cage['id'], 'injection_embryos')
    assert newer['id'] != event['id'] and newer['due'] == '2026-09-16T11:00'


def test_cage_timer_starts_at_collection_and_renewal_uses_actual_time(workflow_client):
    client, clock = workflow_client
    source, bottle = start(client)
    clock['now'] = datetime(2026, 9, 11, 17, 45)
    assert do(client, source, 'injection_collect', '2026-09-11T17:45', female_count=200, male_count=60).status_code == 200
    clock['now'] = datetime(2026, 9, 14, 23, 59)
    assert not any(c['kind'] == 'cage' for c in state(client)['containers'])
    clock['now'] = datetime(2026, 9, 15, 0, 0)
    snapshot = state(client)
    cage = next(c for c in snapshot['containers'] if c['kind'] == 'cage')
    assert cage['status'] == 'planned' and cage['injection_day'] == 4
    assert not any(e['container_id'] == cage['id'] and e['status'] == 'pending' for e in snapshot['events'])
    clock['now'] = datetime(2026, 9, 17, 11)
    assert do(client, bottle, 'injection_transfer', '2026-09-17T11:00').status_code == 200
    event = pending(client, cage['id'], 'injection_renew')
    assert event['due'] == '2026-09-16T00:00'  # late physical transfer does not reset D0
    assert event['scheduled_at'] == '2026-09-16T17:45'
    assert event['all_day'] is True and event['end'] == '2026-09-16T23:59'
    assert do(client, cage, 'injection_renew', '2026-09-17T10:59', event_id=event['id']).status_code == 422
    assert do(client, cage, 'injection_renew', '2026-09-17T11:00', event_id=event['id']).status_code == 200
    assert pending(client, cage['id'], 'injection_embryos')['due'] == '2026-09-17T11:30'


def test_managed_children_cannot_be_activated_or_cooled_with_ordinary_actions(workflow_client):
    client, clock = workflow_client
    source, bottle = start(client)
    for action in ('activate', 'cold', 'warm', 'clear', 'third_instar'):
        response = client.post(f'/api/containers/{bottle["id"]}/actions', json={'action': action, 'at': '2026-09-01T10:00'})
        assert response.status_code == 409, response.text
    payload = {k: bottle[k] for k in ('label', 'genotype', 'notes', 'female_genotype', 'male_genotype', 'temperature_policy', 'template')}
    assert client.put(f'/api/containers/{bottle["id"]}', json={**payload, 'setup_date': '2026-09-02'}).status_code == 409
    payload['notes'] = 'Actual yeast amount recorded here'
    assert client.put(f'/api/containers/{bottle["id"]}', json=payload).status_code == 200
    assert client.get(f'/api/containers/{bottle["id"]}/suggestions').json()['options'] == []


def test_generic_task_done_cannot_bypass_physical_confirmation(workflow_client):
    client, _ = workflow_client
    source, bottle = start(client)
    event = pending(client, source['id'], 'injection_collect')
    response = client.patch(f'/api/events/{event["id"]}', json={'status': 'done'})
    assert response.status_code == 409
    assert next(c for c in state(client)['containers'] if c['id'] == bottle['id'])['status'] == 'planned'


def test_rescheduling_collection_updates_all_day_flag_and_restore(workflow_client):
    client, _ = workflow_client
    source, _ = start(client)
    event = pending(client, source['id'], 'injection_collect')
    assert event['all_day']
    response = client.patch(f'/api/events/{event["id"]}', json={'due': '2026-09-11T09:00', 'end': '2026-09-11T10:00'})
    assert response.status_code == 200 and not response.json()['all_day']
    restored = client.patch(f'/api/events/{event["id"]}', json={'restore': True})
    assert restored.status_code == 200 and restored.json()['all_day']
    assert restored.json()['due'] == '2026-09-11T00:00'


def test_closing_source_cancels_only_unfilled_housing(workflow_client):
    client, clock = workflow_client
    source, bottle = start(client)
    response = client.post(f'/api/containers/{source["id"]}/actions', json={'action': 'discard', 'at': '2026-09-01T10:00'})
    assert response.status_code == 200, response.text
    housing = next(c for c in state(client)['containers'] if c['id'] == bottle['id'])
    assert housing['status'] == 'discarded' and housing['injection']['phase'] == 'finished'
    source, bottle = start(client, label='fresh source')
    clock['now'] = datetime(2026, 9, 11, 10)
    assert do(client, source, 'injection_collect', '2026-09-11T10:00', female_count=200, male_count=50).status_code == 200
    response = client.post(f'/api/containers/{source["id"]}/actions', json={'action': 'discard', 'at': '2026-09-11T10:00'})
    assert response.status_code == 200
    housing = next(c for c in state(client)['containers'] if c['id'] == bottle['id'])
    assert housing['status'] == 'active' and housing['injection']['phase'] == 'conditioning'


def test_cross_requires_explicit_selected_genotype_and_keeps_parent_records(workflow_client):
    client, _ = workflow_client
    source = new_culture(client, workflow={'target_genotype': 'unverified-target'})
    response = client.post(f'/api/containers/{source["id"]}/injection-preparation', json={'at': '2026-09-01T10:00'})
    assert response.status_code == 422
    response = client.post(f'/api/containers/{source["id"]}/injection-preparation', json={'at': '2026-09-01T10:00', 'genotype': 'selected and verified'})
    assert response.status_code == 200
    data = response.json()
    assert data['bottle']['genotype'] == 'selected and verified'
    assert not data['bottle']['female_genotype'] and not data['bottle']['male_genotype']
    assert data['source']['female_genotype'] == source['female_genotype']
