"""User journeys with controlled laboratory time and an isolated SQLite database."""
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from backend import app as module
from backend.test_app import create, snapshot
from backend.test_review import edit

@pytest.fixture
def lab(tmp_path, monkeypatch):
    clock = [datetime.fromisoformat('2026-09-21T09:00')]
    monkeypatch.setattr(module, 'DB_PATH', tmp_path / 'time.db')
    monkeypatch.setattr(module, 'now_of', lambda db: clock[0])
    module.init_db()
    client = TestClient(module.app)
    def advance(value):
        clock[0] = datetime.fromisoformat(value)
        return snapshot(client)
    return client, advance

def test_import_existing_culture_preserves_all_initial_state(lab):
    client, advance = lab
    c = create(client, label='Imported bottle α', kind='bottle', setup_date='2026-09-15', setup_time=None,
               parents='removed', stage='pupae', transfer_index=2, initial_temperature=18, initial_status='active')
    state = advance('2026-09-21T09:00')
    imported = state['containers'][0]
    assert (imported['parents'], imported['stage'], imported['transfer_index'], imported['temperature']) == ('removed','pupae',2,18)
    assert imported['calendar_day'] == 6 and imported['effective_age'] == 3.2
    assert imported['setup_time'] is None and imported['clock']['state'] == 'unknown'
    assert not any(e['kind'] == 'transfer' for e in state['events'])
    assert next(e for e in state['events'] if e['kind'] == 'tissue')['due'] == '2026-09-27T09:00'
    assert client.post(f"/api/containers/{c['id']}/transfer", json={'setup_date':'2026-09-21','female_genotype':'A','male_genotype':'B'}).status_code == 409

@pytest.mark.parametrize('state', ['larvae','pupae','eclosion'])
def test_observation_does_not_invent_a_new_d0(lab, state):
    client, advance = lab
    create(client, setup_date='2026-09-15', setup_time='09:00', stage=state, parents='transferred', transfer_index=1)
    data = advance('2026-09-21T09:00')
    assert data['containers'][0]['calendar_day'] == 6
    assert next(e for e in data['events'] if e['kind'] == 'collect')['due'] == '2026-09-25T09:00'

@pytest.mark.parametrize('changes', [{'transfer_index':-1}, {'transfer_index':21}, {'stage':'adult'}, {'initial_status':'active','setup_date':'2026-09-22'}])
def test_invalid_initial_state_is_rejected_atomically(lab, changes):
    client, advance = lab
    response = client.post('/api/containers', json={'setup_date':'2026-09-21','female_genotype':'A','male_genotype':'B', **changes})
    assert response.status_code == 422
    assert not snapshot(client)['containers']

def test_d0_d2_transfer_d6_bottle_and_d10_three_collection_windows(lab):
    client, advance = lab
    c = create(client, kind='bottle', setup_date='2026-09-21', setup_time='09:00')
    assert snapshot(client)['containers'][0]['calendar_day'] == 0
    advance('2026-09-23T09:00')
    child = client.post(f"/api/containers/{c['id']}/transfer", json={'label':'D2 child','setup_date':'2026-09-23','setup_time':'09:00','female_genotype':'A','male_genotype':'B'}).json()
    data = advance('2026-09-27T09:00')
    source = next(x for x in data['containers'] if x['id'] == c['id'])
    assert source['calendar_day'] == 6 and source['parents'] == 'transferred'
    assert next(x for x in data['containers'] if x['id'] == child['id'])['calendar_day'] == 4
    tissue = next(e for e in data['events'] if e['container_id'] == c['id'] and e['kind'] == 'tissue')
    assert tissue['due'] == '2026-09-27T09:00' and tissue['status'] == 'pending'
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'tissue','at':'2026-09-27T09:00'}).status_code == 200
    for at in ['2026-10-01T09:00','2026-10-01T15:00','2026-10-01T19:00']:
        data = advance(at)
        todays = [e for e in data['events'] if e['container_id'] == c['id'] and e['kind'] == 'collect' and e['due'].startswith('2026-10-01')]
        assert len(todays) == 3
        assert next(e for e in todays if e['due'] == at)['status'] == 'pending'
        assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'collect','at':at,'cleared':True}).status_code == 200
        done = next(e for e in snapshot(client)['events'] if e['due'] == at and e['container_id'] == c['id'])
        assert done['status'] == 'done'
    data = advance('2026-10-02T09:00')
    assert next(x for x in data['containers'] if x['id'] == c['id'])['clock']['state'] == 'elapsed'
    assert len([e for e in data['events'] if e['container_id'] == c['id'] and e['kind'] == 'collect' and e['status'] == 'done']) == 3

def test_cold_days_advance_half_speed_and_actual_warm_reforecasts(lab):
    client, advance = lab
    c = create(client, setup_date='2026-09-21', setup_time='09:00')
    advance('2026-09-23T09:00')
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'cold','at':'2026-09-23T09:00'}).status_code == 200
    data = advance('2026-09-25T09:00')
    assert data['containers'][0]['calendar_day'] == 4 and data['containers'][0]['effective_age'] == 3
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'warm','at':'2026-09-25T09:00'}).status_code == 200
    data = advance('2026-10-02T09:00')
    assert data['containers'][0]['effective_age'] == 10
    assert next(e for e in data['events'] if e['kind'] == 'collect')['due'] == '2026-10-02T09:00'

def test_planned_culture_never_auto_activates_as_time_passes(lab):
    client, advance = lab
    c = create(client, setup_date='2026-09-22', setup_time='09:00')
    assert c['status'] == 'planned'
    data = advance('2026-09-24T10:00')
    assert data['containers'][0]['status'] == 'planned'
    assert client.post(f"/api/containers/{c['id']}/actions", json={'action':'activate','at':'2026-09-24T10:00'}).status_code == 200
    actual = snapshot(client)['containers'][0]
    assert actual['setup_date'] == '2026-09-24' and actual['calendar_day'] == 0

def test_pinned_task_survives_rule_removal_readdition_and_time(lab):
    client, advance = lab
    c = create(client, setup_date='2026-09-21', setup_time='09:00')
    task = next(e for e in snapshot(client)['events'] if e['rule_key'].startswith('collect-2-'))
    client.patch(f"/api/events/{task['id']}", json={'due':'2026-10-04T10:00','end':'2026-10-04T11:00'})
    edit(client, c, template={**c['template'], 'collection_days':1})
    edit(client, c, template=c['template'])
    data = advance('2026-10-04T12:00')
    restored = next(e for e in data['events'] if e['id'] == task['id'])
    assert restored['status'] == 'pending' and restored['pinned'] and restored['due'] == '2026-10-04T10:00'

def test_partial_availability_only_conflicts_affected_collection_windows(lab):
    client, advance = lab
    create(client, setup_date='2026-09-21', setup_time='09:00')
    assert client.put('/api/availability', json={'date':'2026-10-01','kind':'partial','windows':[['09:00','12:00']], 'notes':'Afternoon leave'}).status_code == 200
    data = advance('2026-10-01T09:00')
    windows = [e for e in data['events'] if e['kind'] == 'collect' and e['due'].startswith('2026-10-01')]
    assert [e['conflict'] for e in windows] == [False,True,True]
