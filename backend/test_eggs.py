from datetime import datetime

import pytest
from backend.test_app import client, create, snapshot
from backend import app as module

def laying(client):
    return create(client, kind='egg_laying', purpose='egg_laying')

def batch(client, source, **changes):
    response = client.post(f"/api/containers/{source['id']}/egg-batches", json={
        'label':'Eggs A', 'genotype':'w1118', 'lay_start':'2026-09-08T09:00', 'lay_end':'2026-09-08T13:00', **changes})
    assert response.status_code == 200, response.text
    return response.json()

def collect(client, b):
    response = client.post(f"/api/egg-batches/{b['id']}/actions", json={'action':'collect','at':'2026-09-08T13:30'})
    assert response.status_code == 200, response.text

def dish(client, b=None, **changes):
    return create(client, kind='petri_dish', purpose='dissection', genotype='w1118', setup_date='2026-09-08', setup_time='15:00',
        egg_batch_id=b['id'] if b else None, incubation={'lay_start':'2026-09-08T09:00','lay_end':'2026-09-08T13:00','min_hours':24,'max_hours':30}, **changes)

def test_hourly_dish_uses_full_laying_range_not_transfer_time(client, monkeypatch):
    source = laying(client)
    b = batch(client, source)
    collect(client, b)
    c = dish(client, b)
    data = snapshot(client)
    dish_state = next(x for x in data['containers'] if x['id'] == c['id'])
    assert dish_state['egg_age_hours'] == [25,29]
    assert dish_state['source_id'] == source['id']
    events = [e for e in data['events'] if e['container_id'] == c['id']]
    assert len(events) == 1 and events[0]['kind'] == 'first_instar'
    assert (events[0]['due'], events[0]['end']) == ('2026-09-09T09:00','2026-09-09T19:00')
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026,9,9,20))
    later = snapshot(client)
    assert next(e for e in later['events'] if e['id'] == events[0]['id'])['end'] < later['now']
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'first_instar','at':'2026-09-09T20:00'}).status_code == 200
    observed = snapshot(client)
    assert next(x for x in observed['containers'] if x['id'] == c['id'])['stage'] == 'first_instar'
    assert next(e for e in observed['events'] if e['id'] == events[0]['id'])['status'] == 'done'

def test_one_batch_supplies_multiple_dishes_and_direct_imaging(client):
    source = laying(client)
    b = batch(client, source)
    collect(client, b)
    a, z = dish(client,b), dish(client,b)
    assert a['id'] != z['id'] and a['egg_batch_id'] == z['egg_batch_id']
    response = client.post(f"/api/egg-batches/{b['id']}/actions", json={'action':'use','purpose':'imaging','at':'2026-09-09T10:00','notes':'Aliquot on slide'})
    assert response.status_code == 200
    assert response.json()['status'] == 'collected'
    assert response.json()['uses'][0]['purpose'] == 'imaging'

def test_standalone_dish_and_hourly_temperature_review(client):
    c = dish(client)
    before = snapshot(client)['events'][0]
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'cold','at':'2026-09-08T16:00'}).status_code == 200
    data = snapshot(client)
    assert data['containers'][0]['incubation_window']['review']
    assert data['events'][0]['timing_review']
    assert data['events'][0]['due'] == before['due']
    assert client.get(f"/api/containers/{c['id']}/suggestions").json()['state'] == 'hourly_manual'

def test_pinned_dish_task_keeps_manual_time_but_updates_temperature_warning(client):
    c = dish(client)
    e = snapshot(client)['events'][0]
    client.patch(f"/api/events/{e['id']}", json={'due':'2026-09-09T08:00','end':'2026-09-09T09:00'})
    client.post(f"/api/containers/{c['id']}/actions", json={'action':'cold','at':'2026-09-08T16:00'})
    pinned = snapshot(client)['events'][0]
    assert pinned['due'] == '2026-09-09T08:00' and pinned['timing_review']

def test_laying_container_has_no_vial_cycle_reminders(client):
    source = laying(client)
    assert not snapshot(client)['events']
    b = batch(client, source)
    assert len(snapshot(client)['events']) == 1
    assert snapshot(client)['events'][0]['egg_batch_id'] == b['id']
    assert client.post(f"/api/egg-batches/{b['id']}/actions", json={'action':'collect','at':'2026-09-08T12:00'}).status_code == 409
    collect(client,b)
    assert snapshot(client)['events'][0]['status'] == 'done'
    assert client.post(f"/api/egg-batches/{b['id']}/actions", json={'action':'collect','at':'2026-09-09T10:00'}).status_code == 409

def test_uncollected_batch_cannot_prepare_dish(client):
    b = batch(client, laying(client))
    response = client.post('/api/containers', json={'kind':'petri_dish','purpose':'dissection','genotype':'w','setup_date':'2026-09-09','setup_time':'09:00', 'egg_batch_id':b['id'], 'incubation':{'lay_start':b['lay_start'],'lay_end':b['lay_end']}})
    assert response.status_code == 409
    assert len(snapshot(client)['containers']) == 1

@pytest.mark.parametrize('incubation', [
    {'lay_start':'2026-09-08T09:00','lay_end':'2026-09-08T08:00'},
    {'lay_start':'2026-09-08T09:00','lay_end':'2026-09-08T13:00','min_hours':31,'max_hours':30},
    {'lay_start':'2026-09-08T09:00+08:00','lay_end':'2026-09-08T13:00+08:00'},
])
def test_bad_incubation_input_does_not_write(client, incubation):
    response = client.post('/api/containers', json={'kind':'petri_dish','purpose':'dissection','genotype':'w','setup_date':'2026-09-09','setup_time':'09:00','incubation':incubation})
    assert response.status_code == 422 and not snapshot(client)['containers']

def test_closing_source_cancels_planned_batches_but_preserves_collected_eggs(client):
    source = laying(client)
    collected = batch(client, source)
    collect(client, collected)
    pending = batch(client, source, label='Eggs B')
    client.post(f"/api/containers/{source['id']}/actions", json={'action':'complete','at':'2026-09-09T10:00'})
    states = {b['id']:b['status'] for b in snapshot(client)['egg_batches']}
    assert states == {collected['id']:'collected', pending['id']:'cancelled'}
    assert dish(client, collected)['egg_batch_id'] == collected['id']

def test_reschedule_updates_existing_event_and_preserves_duration(client):
    create(client)
    original = next(e for e in snapshot(client)['events'] if e['kind'] == 'collect')
    before = len(snapshot(client)['events'])
    assert client.patch(f"/api/events/{original['id']}",json={'due':'2026-09-10T09:00'}).status_code == 200
    for _ in range(3):
        data = snapshot(client)
        assert len(data['events']) == before
        matches = [e for e in data['events'] if e['rule_key'] == original['rule_key']]
        assert len(matches) == 1
        assert matches[0]['id'] == original['id'] and matches[0]['pinned']
        assert matches[0]['due'] == '2026-09-10T09:00' and matches[0]['end'] == '2026-09-10T11:00'

def test_moving_only_start_with_old_end_is_a_spanning_event_not_a_duplicate(client):
    create(client)
    original = next(e for e in snapshot(client)['events'] if e['kind'] == 'collect')
    client.patch(f"/api/events/{original['id']}",json={'due':'2026-09-10T09:00', 'end':original['end']})
    matches = [e for e in snapshot(client)['events'] if e['id'] == original['id']]
    assert len(matches) == 1 and matches[0]['due'][:10] != matches[0]['end'][:10]
