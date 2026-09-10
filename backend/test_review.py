"""Regression cases discovered by realistic user-flow review (2026-09-09)."""
from backend.test_app import client, create, snapshot
from backend.domain import DEFAULT_TEMPLATE, DEFAULT_SETTINGS, event_conflict
from backend import app as module

def edit(client, culture, **changes):
    body = {k: culture[k] for k in ('label', 'genotype', 'female_genotype', 'male_genotype', 'notes', 'temperature_policy', 'template')}
    body.update(changes)
    return client.put(f"/api/containers/{culture['id']}", json=body)

def test_removed_then_readded_windows_restore_pending_reminders_on_one_day(client):
    c = create(client)
    assert edit(client, c, template={**c['template'], 'windows': [['09:00','11:00']]}).status_code == 200
    assert edit(client, c, template=c['template']).status_code == 200
    assert len([e for e in snapshot(client)['events'] if e['kind'] == 'collect' and e['status'] == 'pending']) == 3

def test_removing_a_collection_window_does_not_transfer_its_completed_status(client):
    c = create(client)
    morning = next(e for e in snapshot(client)['events'] if e['kind'] == 'collect')
    client.patch(f"/api/events/{morning['id']}", json={'status':'done'})
    assert edit(client, c, template={**c['template'], 'windows': [['15:00','15:30'], ['19:00','21:00']]}).status_code == 200
    upcoming = [e for e in snapshot(client)['events'] if e['kind'] == 'collect' and e['status'] == 'pending']
    assert len(upcoming) == 2
    assert any(e['due'] == '2026-09-11T15:00' for e in upcoming)

def test_offset_timestamp_cannot_poison_workspace(client):
    response = client.post('/api/events', json={'title':'Lab appointment', 'due':'2026-09-10T09:00:00+08:00','end':'2026-09-10T10:00:00+08:00'})
    assert response.status_code == 422
    assert client.get('/api/state').status_code == 200

def test_archive_cannot_accept_new_pending_reminder(client):
    c = create(client)
    client.post(f"/api/containers/{c['id']}/actions", json={'action':'complete','at':'2026-09-09T10:00'})
    assert client.post('/api/events', json={'container_id':c['id'],'title':'Inspect food','due':'2026-09-10T09:00','end':'2026-09-10T10:00'}).status_code == 409

def test_direct_tissue_operation_completes_matching_reminder(client):
    c = create(client, kind='bottle', setup_date='2026-09-03')
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'tissue','at':'2026-09-09T13:00'}).status_code == 200
    assert next(e for e in snapshot(client)['events'] if e['kind'] == 'tissue')['status'] == 'done'

def test_completed_collection_does_not_block_temperature_search(client):
    c = create(client, setup_date='2026-09-03', template={**DEFAULT_TEMPLATE,'collection_days':1})
    for e in snapshot(client)['events']:
        if e['critical']:
            client.patch(f"/api/events/{e['id']}", json={'status':'disabled'})
    assert client.get(f"/api/containers/{c['id']}/suggestions").json()['state'] == 'clear'

def test_transfer_cannot_silently_drop_temperature_restriction(client):
    c = create(client, temperature_policy='forbidden')
    body = {'setup_date':'2026-09-05','purpose':'cross','female_genotype':c['female_genotype'],'male_genotype':c['male_genotype']}
    child = client.post(f"/api/containers/{c['id']}/transfer", json=body).json()
    assert child['temperature_policy'] == 'forbidden'

def test_edited_label_is_normalized_before_unique_check(client):
    create(client, label='B01')
    c = create(client, label='B02')
    assert edit(client, c, label=' B01 ').status_code == 409

def test_tiny_development_rate_is_rejected_before_overflow(client):
    settings = snapshot(client)['settings']
    settings['template']['rate18'] = 1e-300
    assert client.put('/api/settings', json=settings).status_code == 422

def test_overnight_custom_task_can_use_next_days_availability():
    e = {'due':'2026-09-12T23:00','end':'2026-09-14T12:00'}
    assert not event_conflict(e, DEFAULT_SETTINGS, [])

def test_setup_planner_keeps_an_already_valid_requested_time(client):
    c = create(client, setup_date='2026-09-14', setup_time='16:00', purpose='stock',genotype='w1118')
    suggestions = client.get(f"/api/containers/{c['id']}/suggestions").json()
    assert suggestions['options'][0]['setup_at'] == '2026-09-14T16:00'

def test_legacy_collection_key_upgrade_preserves_identity_and_history(client):
    create(client)
    events = [e for e in snapshot(client)['events'] if e['kind'] == 'collect']
    with module.database() as db:
        for index, e in enumerate(events):
            e['rule_key'] = f'collect-{index // 3}-{index % 3}'
            if index == 0:
                e['status'] = 'done'
            if index == 1:
                e.update(pinned=True, due='2026-09-28T16:00', end='2026-09-28T17:00')
            module.save_event(db, e)
    migrated = {e['id']:e for e in snapshot(client)['events'] if e['kind'] == 'collect'}
    assert len(migrated) == 3
    assert migrated[events[0]['id']]['status'] == 'done'
    pinned = migrated[events[1]['id']]
    assert pinned['rule_key'] == 'collect-0-15:00-15:30'
    assert pinned['pinned'] and pinned['due'] == '2026-09-28T16:00'
