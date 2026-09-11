"""Continuation reminders after real parent transfers, using isolated cultures."""
from datetime import datetime

import pytest

from backend import app as module
from backend.test_app import client, create, snapshot
from backend.test_review import edit


def move(client, source, kind=None, at='2026-09-03T13:15', **changes):
    day, time = at.split('T')
    return client.post(f"/api/containers/{source['id']}/transfer", json={
        'kind': kind or source['kind'], 'purpose': source['purpose'],
        'genotype': source['genotype'], 'female_genotype': source['female_genotype'],
        'male_genotype': source['male_genotype'], 'setup_date': day, 'setup_time': time,
        'mode': 'transfer', **changes,
    })


def transfer_events(client, cid):
    return [event for event in snapshot(client)['events']
            if event['container_id'] == cid and event['kind'] == 'transfer']


@pytest.mark.parametrize('source_kind', ['vial', 'bottle'])
@pytest.mark.parametrize('destination_kind', ['vial', 'bottle'])
def test_manual_stock_transfer_starts_next_reminder_and_stops_at_limit(client, source_kind, destination_kind):
    source = create(client, kind=source_kind, purpose='stock', genotype='w1118')
    assert source['workflow']['transfer_enabled'] is False
    assert not transfer_events(client, source['id'])

    response = move(client, source, destination_kind)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['parents'] == 'present' and child['transfer_index'] == 1
    assert child['cohort_id'] == source['cohort_id']
    assert child['workflow']['transfer_enabled'] is True
    reminder, = transfer_events(client, child['id'])
    assert (reminder['due'], reminder['end'], reminder['status']) == (
        '2026-09-06T13:15', '2026-09-06T13:15', 'pending')
    parent = next(item for item in snapshot(client)['containers'] if item['id'] == source['id'])
    assert parent['parents'] == 'transferred' and parent['workflow'] == source['workflow']

    second = move(client, child, source_kind, at='2026-09-05T11:20')
    assert second.status_code == 200, second.text
    last = second.json()
    assert last['transfer_index'] == 2 and last['parents'] == 'present'
    assert not transfer_events(client, last['id'])
    assert transfer_events(client, child['id'])[0]['status'] == 'done'
    assert move(client, last, at='2026-09-07T09:00').status_code == 409


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('purpose', ['cross', 'virgin', 'larvae'])
def test_same_parent_continuation_enables_reminder_without_changing_other_workflow_rules(client, kind, purpose):
    source = create(client, kind=kind, purpose=purpose, genotype='w1118',
        workflow={'transfer_enabled': False, 'cross_goal': 'third_instar', 'third_instar_day': 6,
                  'target_genotype': 'Expected F1', 'remove_day': 4})
    response = move(client, source)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['workflow'] == {**source['workflow'], 'transfer_enabled': True}
    assert transfer_events(client, child['id'])[0]['due'] == '2026-09-06T13:15'


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_explicit_transfer_opt_out_and_next_generation_keep_their_own_policy(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118')
    response = move(client, source, workflow={**source['workflow'], 'transfer_enabled': False})
    assert response.status_code == 200, response.text
    assert not transfer_events(client, response.json()['id'])

    generation = move(client, source, mode='generation')
    assert generation.status_code == 200, generation.text
    assert generation.json()['transfer_index'] == 0
    assert generation.json()['workflow']['transfer_enabled'] is False
    assert not transfer_events(client, generation.json()['id'])


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_custom_transfer_interval_stays_calendar_based_as_time_passes(client, kind, monkeypatch):
    source = create(client, kind=kind, purpose='stock', genotype='w1118', template={'transfer_day': 2})
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 3, 13, 15))
    response = move(client, source, initial_temperature=18)
    assert response.status_code == 200, response.text
    child = response.json()
    initial, = transfer_events(client, child['id'])
    assert initial['due'] == '2026-09-05T13:15'
    for stamp in ['2026-09-04T14:00', '2026-09-05T13:15', '2026-09-06T09:00']:
        monkeypatch.setattr(module, 'now_of', lambda db, stamp=stamp: datetime.fromisoformat(stamp))
        current, = transfer_events(client, child['id'])
        assert current == initial


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_continuation_reschedule_and_disable_survive_reconciliation(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118')
    child = move(client, source).json()
    reminder, = transfer_events(client, child['id'])
    response = client.patch(f"/api/events/{reminder['id']}", json={
        'due': '2026-09-07T10:00', 'end': '2026-09-07T11:00'})
    assert response.status_code == 200
    pinned, = transfer_events(client, child['id'])
    assert pinned['id'] == reminder['id'] and pinned['pinned']
    assert pinned['due'] == '2026-09-07T10:00'
    assert edit(client, child, notes='Keep the rescheduled transfer window').status_code == 200
    assert transfer_events(client, child['id'])[0]['due'] == '2026-09-07T10:00'
    assert client.patch(f"/api/events/{reminder['id']}", json={'status': 'disabled'}).status_code == 200
    assert transfer_events(client, child['id'])[0]['status'] == 'disabled'


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_existing_parent_count_or_absence_prevents_extra_transfers(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118', transfer_index=1)
    response = move(client, source)
    assert response.status_code == 200
    assert response.json()['transfer_index'] == 2
    assert not transfer_events(client, response.json()['id'])
    removed = create(client, kind=kind, purpose='stock', genotype='w1118', parents='removed')
    assert move(client, removed).status_code == 409


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_legacy_stock_transfer_starts_next_reminder(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118')
    with module.database() as db:
        legacy = module.get_container(db, source['id'])
        legacy['workflow'] = None
        module.save_container(db, legacy)
        module.reconcile(db, legacy)
    response = move(client, legacy)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['transfer_index'] == 1 and child['workflow']['transfer_enabled'] is True
    reminder, = transfer_events(client, child['id'])
    assert reminder['due'] == '2026-09-06T13:15' and reminder['status'] == 'pending'
    parent = next(item for item in snapshot(client)['containers'] if item['id'] == source['id'])
    assert parent['workflow'] is None and parent['parents'] == 'transferred'


@pytest.mark.parametrize('source_kind', ['vial', 'bottle'])
@pytest.mark.parametrize('destination_kind', ['vial', 'bottle'])
def test_stock_renewal_creates_selected_container_and_restarts_cohort(client, source_kind, destination_kind):
    source = create(client, kind=source_kind, purpose='stock', genotype='w1118; UAS-X',
                    transfer_index=2, parents='removed', stage='eclosion',
                    temperature_policy='forbidden', template={'stock_interval': 9})
    original = {event['id']: event for event in snapshot(client)['events']
                if event['container_id'] == source['id']}
    renewal, = [event for event in original.values() if event['kind'] == 'stock']
    assert renewal['status'] == 'pending'

    response = move(client, source, destination_kind, at='2026-09-09T11:45', mode='generation')
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['kind'] == destination_kind and child['purpose'] == 'stock'
    assert child['genotype'] == source['genotype']
    assert child['source_id'] == source['id'] and child['cohort_id'] != source['cohort_id']
    assert child['transfer_index'] == 0 and child['parents'] == 'present'
    assert child['stage'] == 'unobserved' and child['status'] == 'active'
    assert (child['setup_date'], child['setup_time']) == ('2026-09-09', '11:45')
    assert child['template'] == source['template'] and child['workflow'] == source['workflow']
    assert child['temperature_policy'] == 'forbidden'

    state = snapshot(client)
    parent = next(item for item in state['containers'] if item['id'] == source['id'])
    for field in ('parents', 'stage', 'transfer_index', 'cohort_id', 'setup_date', 'setup_time'):
        assert parent[field] == source[field]
    assert any(item['action'] == 'generation' and item['notes'] == child['label'] for item in parent['logs'])
    after = {event['id']: event for event in state['events'] if event['container_id'] == source['id']}
    assert after == {eid: {**event, 'status': 'done'} if eid == renewal['id'] else event
                     for eid, event in original.items()}
    child_events = [event for event in state['events'] if event['container_id'] == child['id']]
    next_renewal, = [event for event in child_events if event['kind'] == 'stock']
    assert next_renewal['due'] == '2026-09-18T09:00' and next_renewal['status'] == 'pending'
    assert not any(event['kind'] == 'transfer' for event in child_events)
    assert any(event['kind'] == ('tissue' if destination_kind == 'bottle' else 'check') for event in child_events)


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_invalid_stock_renewal_keeps_original_reminder_and_creates_nothing(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118', transfer_index=2)
    before = snapshot(client)
    response = move(client, source, at='2026-09-10T10:00', mode='generation')
    assert response.status_code == 422
    assert snapshot(client) == before


def test_stock_renewal_undo_restores_reminder_after_mistaken_child_is_deleted(client, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    source = create(client, kind='bottle', purpose='stock', genotype='w1118', transfer_index=2)
    before = {event['id']: event for event in snapshot(client)['events']
              if event['container_id'] == source['id']}
    response = move(client, source, 'vial', mode='generation')
    assert response.status_code == 200, response.text
    child = response.json()
    parent = next(item for item in snapshot(client)['containers'] if item['id'] == source['id'])
    activity = next(item for item in parent['logs'] if item['action'] == 'generation')
    activity_url = f"/api/containers/{source['id']}/activities/{activity['id']}"
    preview = client.get(activity_url + '/delete-preview').json()
    assert not preview['can_delete'] and 'linked_container' in preview['blockers']

    child_url = f"/api/containers/{child['id']}"
    preview = client.get(child_url + '/delete-preview').json()
    response = client.request('DELETE', child_url, json={
        'confirmation_label': child['label'], 'fingerprint': preview['fingerprint'],
    })
    assert response.status_code == 200, response.text
    preview = client.get(activity_url + '/delete-preview').json()
    assert preview['can_delete'], preview
    response = client.request('DELETE', activity_url, json={'fingerprint': preview['fingerprint']})
    assert response.status_code == 200, response.text
    state = snapshot(client)
    assert {event['id']: event for event in state['events'] if event['container_id'] == source['id']} == before
    parent = next(item for item in state['containers'] if item['id'] == source['id'])
    assert parent['transfer_index'] == 2 and parent['cohort_id'] == source['cohort_id']
