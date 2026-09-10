from datetime import datetime

import pytest
from backend import app as module
from backend.test_app import client, create, snapshot


def derive(client, source, **changes):
    return client.post(f"/api/containers/{source['id']}/egg-laying", json={
        'cohort_mode': 'generation', 'setup_date': '2026-09-09', 'setup_time': '13:00', **changes,
    })


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_stock_offspring_inherit_metadata_but_start_independent_cohort(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118', notes='Diet A',
                    parents='removed', stage='eclosion', transfer_index=2, temperature_policy='forbidden')
    before = snapshot(client)
    response = derive(client, source)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['kind'] == child['purpose'] == 'egg_laying'
    assert child['female_genotype'] == child['male_genotype'] == 'w1118'
    assert child['notes'] == 'Diet A' and child['temperature_policy'] == 'forbidden'
    assert child['source_id'] == source['id'] and child['source_relation'] == 'egg_laying_generation'
    assert child['cohort_id'] != source['cohort_id'] and child['transfer_index'] == 0
    assert child['parents'] == 'present' and child['stage'] == 'unobserved'
    after = snapshot(client)
    old = next(c for c in after['containers'] if c['id'] == source['id'])
    assert old['setup_date'] == source['setup_date'] and old['parents'] == 'removed'
    assert after['events'] == before['events']
    assert next(c for c in after['containers'] if c['id'] == child['id'])['calendar_day'] == 0


def test_same_parents_keep_cohort_increment_transfer_and_complete_only_transfer_task(client):
    source = create(client, transfer_index=1)
    before = snapshot(client)
    response = derive(client, source, cohort_mode='transfer')
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['cohort_id'] == source['cohort_id'] and child['transfer_index'] == 2
    assert child['female_genotype'] == source['female_genotype']
    assert child['male_genotype'] == source['male_genotype']
    for _ in range(2):
        after = snapshot(client)
        assert next(c for c in after['containers'] if c['id'] == source['id'])['parents'] == 'transferred'
        assert len(after['events']) == len(before['events'])
        for event in after['events']:
            original = next(e for e in before['events'] if e['id'] == event['id'])
            if event['kind'] == 'remove':
                assert event['status'] == 'cancelled' and event['due'] == original['due']
            else:
                assert event == ({**original, 'status': 'done', 'conflict': False} if event['kind'] == 'transfer' else original)
    assert derive(client, source, cohort_mode='transfer').status_code == 409


def test_cross_offspring_require_selected_genotypes_and_allow_edited_metadata(client):
    source = create(client, notes='Source notes')
    assert derive(client, source).json()['detail'] == 'parent_genotypes_required'
    assert len(snapshot(client)['containers']) == 1
    response = derive(client, source, female_genotype='nub-GAL4/+; UAS-X/+', male_genotype='w1118',
                      notes='Selected adults', initial_temperature=18, temperature_policy='forbidden')
    assert response.status_code == 200
    child = response.json()
    assert child['female_genotype'] == 'nub-GAL4/+; UAS-X/+' and child['initial_temperature'] == 18
    assert child['notes'] == 'Selected adults' and child['temperature_policy'] == 'forbidden'
    old = next(c for c in snapshot(client)['containers'] if c['id'] == source['id'])
    assert old['notes'] == 'Source notes' and old['parents'] == 'present'


def test_backdated_setup_inherits_temperature_at_setup_not_latest_move(client):
    source = create(client, purpose='stock', genotype='w')
    client.post(f"/api/containers/{source['id']}/actions", json={'action':'cold', 'at':'2026-09-08T10:00'})
    client.post(f"/api/containers/{source['id']}/actions", json={'action':'warm', 'at':'2026-09-09T12:00'})
    child = derive(client, source, setup_date='2026-09-08', setup_time='14:00').json()
    assert child['initial_temperature'] == 18
    assert not next(c for c in snapshot(client)['containers'] if c['id'] == child['id'])['temperatures']


@pytest.mark.parametrize('changes, code', [
    ({'setup_date':'2026-08-31'}, 422), ({'setup_time':'15:00'}, 422),
    ({'setup_time':'garbage'}, 422), ({'cohort_mode':'copy'}, 422),
    ({'female_genotype':' '}, 422), ({'initial_temperature':20}, 422),
])
def test_invalid_creation_is_atomic(client, changes, code):
    source = create(client, purpose='stock', genotype='w')
    before = snapshot(client)
    assert derive(client, source, **changes).status_code == code
    assert snapshot(client) == before


@pytest.mark.parametrize('changes', [{'parents':'removed'}, {'parents':'transferred'}, {'transfer_index':2}])
def test_original_parent_transfer_respects_presence_and_limit(client, changes):
    source = create(client, **changes)
    before = snapshot(client)
    assert derive(client, source, cohort_mode='transfer').status_code == 409
    assert snapshot(client) == before


def test_duplicate_label_rolls_back_source_changes(client):
    source = create(client)
    before = snapshot(client)
    assert derive(client, source, cohort_mode='transfer', label=source['label']).status_code == 409
    assert snapshot(client) == before


def test_ineligible_sources_are_rejected(client):
    source = create(client, kind='egg_laying', purpose='egg_laying')
    assert derive(client, source).json()['detail'] == 'egg_laying_source_required'
    for status in ('planned', 'completed'):
        source = create(client, initial_status='planned' if status == 'planned' else 'active')
        if status == 'completed':
            client.post(f"/api/containers/{source['id']}/actions", json={'action':'complete','at':'2026-09-09T12:00'})
        assert derive(client, source).status_code == 409


def test_inherited_source_connects_batch_dish_and_hourly_time_flow(client, monkeypatch):
    source = create(client, purpose='stock', genotype='w')
    child = derive(client, source, setup_time='09:00').json()
    batch = client.post(f"/api/containers/{child['id']}/egg-batches", json={
        'label':'Morning eggs','genotype':'w','lay_start':'2026-09-09T09:00','lay_end':'2026-09-09T13:00',
    }).json()
    assert client.post(f"/api/egg-batches/{batch['id']}/actions", json={'action':'collect','at':'2026-09-09T13:30'}).status_code == 200
    dish = create(client, kind='petri_dish', purpose='dissection', genotype='w', setup_date='2026-09-09',
                  setup_time='14:00', egg_batch_id=batch['id'],
                  incubation={'lay_start':batch['lay_start'], 'lay_end':batch['lay_end']})
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026,9,10,10))
    later = snapshot(client)
    dish_state = next(c for c in later['containers'] if c['id'] == dish['id'])
    assert dish_state['egg_age_hours'] == [21,25]
    assert dish_state['source_id'] == child['id']
    assert dish_state['incubation_window']['start'] == '2026-09-10T09:00'
    assert next(c for c in later['containers'] if c['id'] == child['id'])['source_id'] == source['id']
