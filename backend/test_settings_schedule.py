"""Saving protocol settings updates existing schedules in one transaction."""
from copy import deepcopy
from datetime import datetime, timedelta
import json

import pytest

from backend import app as module
from backend.test_workflows import workflow_client, new_culture, state, events_for


def save_settings(client, **changes):
    settings = state(client)['settings']
    settings['template'].update(changes)
    response = client.put('/api/settings', json=settings)
    assert response.status_code == 200, response.text
    return settings


def stored_events(culture):
    with module.database() as db:
        return {e['id']: e for row in db.execute('SELECT payload FROM events WHERE container_id=?', (culture['id'],))
                for e in [json.loads(row[0])]}


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('temperature', [25, 18])
@pytest.mark.parametrize('setup_date', ['2026-09-01', '2026-09-20'])
def test_settings_recalculate_existing_active_and_planned_cultures_immediately(
    workflow_client, kind, temperature, setup_date,
):
    client, _ = workflow_client
    cultures = [new_culture(client, kind=kind, purpose=purpose, genotype='w1118',
                            initial_temperature=temperature, setup_date=setup_date,
                            setup_time='09:00') for purpose in ('virgin', 'stock')]
    originals = {c['id']: stored_events(c) for c in cultures}
    save_settings(client, transfer_day=4, check_day=7, watch_day=10, collection_day=12, stock_interval=13)
    # Inspect the committed database before /state can mask lazy reconciliation.
    for c in cultures:
        updated = stored_events(c)
        assert updated.keys() == originals[c['id']].keys()
        for event in updated.values():
            target = {'transfer': 4, 'check': 7, 'tissue': 7, 'watch': 10, 'collect': 12, 'stock': 13}
            if event['kind'] not in target:
                continue
            days = target[event['kind']]
            if temperature == 18 and event['basis'] == 'development':
                days *= 2
            expected = datetime.fromisoformat(setup_date) + timedelta(days=days)
            assert event['due'][:10] == expected.date().isoformat()
        assert len([e for e in updated.values() if e['kind'] == 'collect']) == (3 if c['purpose'] == 'virgin' else 0)
        assert stored_events(c) == {e['id']: {k: v for k, v in e.items() if k != 'conflict'}
                                    for e in events_for(client, c)}


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_settings_use_full_cold_history_and_later_actual_warm(workflow_client, kind):
    client, clock = workflow_client
    c = new_culture(client, kind=kind, purpose='virgin', genotype='w1118', setup_time='09:00')
    clock['now'] = datetime(2026, 9, 3, 9)
    assert client.post(f"/api/containers/{c['id']}/actions", json={
        'action': 'cold', 'at': '2026-09-03T09:00'}).status_code == 200
    save_settings(client, collection_day=12)
    assert {e['due'][:10] for e in events_for(client, c, 'collect')} == {'2026-09-23'}
    clock['now'] = datetime(2026, 9, 5, 9)
    assert client.post(f"/api/containers/{c['id']}/actions", json={
        'action': 'warm', 'at': '2026-09-05T09:00'}).status_code == 200
    assert {e['due'][:10] for e in events_for(client, c, 'collect')} == {'2026-09-14'}


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_rate_change_reaches_existing_l3_and_preserves_its_protocol(workflow_client, kind):
    client, _ = workflow_client
    c = new_culture(client, kind=kind, purpose='larvae', genotype='w1118', initial_temperature=18)
    event = events_for(client, c, 'third_instar')[0]
    save_settings(client, rate18=0.25)
    changed = events_for(client, c, 'third_instar')[0]
    assert changed['id'] == event['id'] and changed['due'] == '2026-09-21T09:00'
    assert state(client)['containers'][0]['workflow'] == c['workflow']


def test_affected_reschedules_reset_but_history_custom_and_unrelated_pins_survive(workflow_client):
    client, _ = workflow_client
    c = new_culture(client, purpose='virgin', genotype='w1118')
    collects = events_for(client, c, 'collect')
    for event, change in zip(collects, [
        {'due': '2026-09-29T13:00', 'end': '2026-09-29T14:00'},
        {'status': 'done'}, {'status': 'disabled'},
    ]):
        assert client.patch(f"/api/events/{event['id']}", json=change).status_code == 200
    check = events_for(client, c, 'check')[0]
    assert client.patch(f"/api/events/{check['id']}", json={'due': '2026-09-25T09:00'}).status_code == 200
    assert client.post('/api/events', json={'container_id': c['id'], 'title': 'Custom task',
                                           'due': '2026-09-26T09:00', 'end': '2026-09-26T10:00'}).status_code == 200
    before = stored_events(c)
    save_settings(client, collection_day=12)
    after = stored_events(c)
    changed = after[collects[0]['id']]
    assert (changed['due'], changed['end'], changed['pinned']) == ('2026-09-13T09:00', '2026-09-13T11:00', False)
    assert after.keys() == before.keys()
    assert all(after[eid] == e for eid, e in before.items() if eid != changed['id'])


def test_window_changes_preserve_three_slot_ids_without_reopening_completed_work(workflow_client):
    client, _ = workflow_client
    c = new_culture(client, purpose='virgin', genotype='w1118')
    original = events_for(client, c, 'collect')
    assert client.patch(f"/api/events/{original[0]['id']}", json={'status': 'done'}).status_code == 200
    save_settings(client, windows=[['08:00', '10:00'], ['14:00', '14:30'], ['18:00', '20:00']])
    after = {e['id']: e for e in events_for(client, c, 'collect')}
    assert after.keys() == {e['id'] for e in original}
    assert after[original[0]['id']]['status'] == 'done'
    assert after[original[0]['id']]['due'] == original[0]['due']
    assert after[original[1]['id']]['due'] == '2026-09-11T14:00'
    assert after[original[2]['id']]['due'] == '2026-09-11T18:00'


def test_only_changed_parameters_propagate_and_general_settings_leave_protocols_alone(workflow_client):
    client, _ = workflow_client
    template = deepcopy(state(client)['settings']['template'])
    template.update(check_day=8, collection_day=15)
    c = new_culture(client, purpose='virgin', genotype='w1118', template=template)
    before = stored_events(c)
    settings = state(client)['settings']
    settings['locale'] = 'fr'
    assert client.put('/api/settings', json=settings).status_code == 200
    assert stored_events(c) == before
    save_settings(client, collection_day=12)
    current = state(client)['containers'][0]
    assert current['template']['collection_day'] == 12
    assert current['template']['check_day'] == 8
    assert current['workflow'] == c['workflow']


def test_invalid_merged_protocol_rolls_back_settings_and_all_cultures(workflow_client):
    client, _ = workflow_client
    new_culture(client, purpose='virgin', genotype='w1118')
    template = deepcopy(state(client)['settings']['template'])
    template.update(watch_day=14, collection_day=15)
    new_culture(client, purpose='virgin', genotype='w1118', template=template)
    before = state(client)
    settings = deepcopy(before['settings'])
    settings['template']['collection_day'] = 12
    response = client.put('/api/settings', json=settings)
    assert response.status_code == 409 and response.json()['detail'] == 'settings_protocol_conflict'
    assert state(client) == before


def test_closed_culture_records_are_not_rewritten(workflow_client):
    client, _ = workflow_client
    c = new_culture(client, purpose='virgin', genotype='w1118')
    assert client.post(f"/api/containers/{c['id']}/actions", json={
        'action': 'complete', 'at': '2026-09-01T10:00'}).status_code == 200
    before = state(client)
    save_settings(client, check_day=7, collection_day=12)
    after = state(client)
    assert after['containers'] == before['containers']
    assert after['events'] == before['events']


def test_linked_offspring_readiness_updates_immediately_but_egg_setup_stays_fixed(workflow_client):
    client, _ = workflow_client
    c = new_culture(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{c['id']}/egg-laying", json={
        'adult_source': 'offspring', 'genotype': 'w1118', 'initial_status': 'planned',
        'setup_date': '2026-09-16', 'setup_time': '12:00',
    })
    assert response.status_code == 200, response.text
    child = response.json()
    before = stored_events(child)
    ready = next(e for e in before.values() if e['kind'] == 'offspring_ready')
    assert client.patch(f"/api/events/{ready['id']}", json={'due': '2026-09-20T09:00'}).status_code == 200
    save_settings(client, collection_day=12)
    after = stored_events(child)
    assert after[ready['id']]['due'] == '2026-09-13T10:00'
    assert not after[ready['id']]['pinned']
    assert all(after[eid] == event for eid, event in before.items() if eid != ready['id'])
