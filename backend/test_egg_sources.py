"""Known egg-laying adults, subset selection, and explicitly started plans."""
from datetime import datetime

import pytest
from backend import app as module
from backend.test_app import client, create, snapshot


def derive(client, source, **changes):
    return client.post(f"/api/containers/{source['id']}/egg-laying", json={
        'adult_source': 'offspring', 'genotype': 'w1118',
        'setup_date': '2026-09-09', 'setup_time': '13:00', **changes,
    })


def current(client, culture):
    return next(c for c in snapshot(client)['containers'] if c['id'] == culture['id'])


def events_for(client, culture):
    return [e for e in snapshot(client)['events'] if e['container_id'] == culture['id']]


def edit_body(culture, **changes):
    return {key: culture[key] for key in (
        'label', 'genotype', 'notes', 'temperature_policy', 'template'
    )} | changes


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_stock_offspring_inherit_metadata_but_start_independent_cohort(client, kind):
    source = create(client, kind=kind, purpose='stock', genotype='w1118', notes='Diet A',
                    parents='removed', stage='eclosion', transfer_index=2, temperature_policy='forbidden')
    before = events_for(client, source)
    response = derive(client, source)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['kind'] == child['purpose'] == 'egg_laying'
    assert child['genotype'] == 'w1118'
    assert not child['female_genotype'] and not child['male_genotype']
    assert child['notes'] == 'Diet A' and child['temperature_policy'] == 'forbidden'
    assert child['source_id'] == source['id'] and child['adult_source'] == 'offspring'
    assert child['cohort_id'] != source['cohort_id'] and child['transfer_index'] == 0
    assert child['parents'] == 'present' and child['stage'] == 'unobserved'
    old = current(client, source)
    assert old['setup_date'] == source['setup_date'] and old['parents'] == 'removed'
    assert events_for(client, source) == before
    assert not events_for(client, child)


def test_selected_parents_preserve_source_adults_and_all_source_tasks(client):
    source = create(client, transfer_index=1)
    before = events_for(client, source)
    response = derive(client, source, adult_source='parents', genotype='Selected known line')
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['cohort_id'] == source['cohort_id'] and child['transfer_index'] == 2
    assert child['genotype'] == 'Selected known line' and child['adult_source'] == 'parents'
    for _ in range(2):
        assert current(client, source)['parents'] == 'present'
        assert events_for(client, source) == before
    assert derive(client, source, adult_source='parents').status_code == 200
    assert events_for(client, source) == before


@pytest.mark.parametrize('changes', [{'parents': 'removed'}, {'parents': 'transferred'}, {'transfer_index': 2}])
def test_user_selects_parent_source_without_presence_or_transfer_limit_gate(client, changes):
    source = create(client, **changes)
    before = events_for(client, source)
    response = derive(client, source, adult_source='parents')
    assert response.status_code == 200, response.text
    assert response.json()['transfer_index'] == source['transfer_index'] + 1
    assert current(client, source)['parents'] == source['parents']
    assert events_for(client, source) == before


def test_cross_offspring_use_one_user_confirmed_genotype(client):
    source = create(client, notes='Source notes')
    response = derive(client, source, genotype='nub-GAL4/+; UAS-X/+',
                      notes='Selected adults', initial_temperature=18, temperature_policy='forbidden')
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['genotype'] == 'nub-GAL4/+; UAS-X/+' and child['initial_temperature'] == 18
    assert not child['female_genotype'] and not child['male_genotype']
    assert child['notes'] == 'Selected adults' and child['temperature_policy'] == 'forbidden'
    old = current(client, source)
    assert old['female_genotype'] == source['female_genotype'] and old['male_genotype'] == source['male_genotype']
    assert old['notes'] == 'Source notes' and old['parents'] == 'present'


def test_backdated_setup_inherits_temperature_at_setup_not_latest_move(client):
    source = create(client, purpose='stock', genotype='w')
    client.post(f"/api/containers/{source['id']}/actions", json={'action': 'cold', 'at': '2026-09-08T10:00'})
    client.post(f"/api/containers/{source['id']}/actions", json={'action': 'warm', 'at': '2026-09-09T12:00'})
    response = derive(client, source, setup_date='2026-09-08', setup_time='14:00')
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['initial_temperature'] == 18
    assert not current(client, child)['temperatures']


@pytest.mark.parametrize('changes', [
    {'setup_date': '2026-08-31'}, {'setup_time': '15:00'},
    {'setup_time': 'garbage'}, {'setup_time': None}, {'setup_time': ''},
    {'adult_source': 'all'}, {'genotype': ' '}, {'initial_temperature': 20},
])
def test_invalid_creation_is_atomic(client, changes):
    source = create(client, purpose='stock', genotype='w')
    before = snapshot(client)
    assert derive(client, source, **changes).status_code == 422
    assert snapshot(client) == before


def test_missing_known_genotype_cannot_be_inferred_from_cross_or_old_parent_fields(client):
    source = create(client)
    for payload in [
        {'adult_source': 'offspring'},
        {'adult_source': 'parents', 'female_genotype': 'w', 'male_genotype': 'w'},
        {'cohort_mode': 'transfer', 'genotype': 'w'},
    ]:
        response = client.post(f"/api/containers/{source['id']}/egg-laying", json={
            'setup_date': '2026-09-09', 'setup_time': '13:00', **payload,
        })
        assert response.status_code == 422, response.text
    assert len(snapshot(client)['containers']) == 1


def test_duplicate_label_rolls_back_source_changes(client):
    source = create(client)
    before = snapshot(client)
    assert derive(client, source, adult_source='parents', label=source['label']).status_code == 409
    assert snapshot(client) == before


def test_non_culture_and_closed_sources_are_rejected(client):
    source = create(client, kind='egg_laying', purpose='egg_laying', genotype='w')
    assert derive(client, source).json()['detail'] == 'egg_laying_source_required'
    source = create(client)
    client.post(f"/api/containers/{source['id']}/actions", json={'action': 'complete', 'at': '2026-09-09T12:00'})
    assert derive(client, source).status_code == 409


def test_planned_offspring_show_temperature_sensitive_source_estimate(client):
    source = create(client, purpose='stock', genotype='w')
    before = current(client, source)['eclosion_estimate']
    assert before['at'] == '2026-09-11T10:00' and before['basis'] == 'estimated'
    response = derive(client, source, initial_status='planned', setup_date='2026-09-13', setup_time='10:15')
    assert response.status_code == 200, response.text
    child = response.json()
    assert current(client, child)['source_eclosion_estimate'] == before
    events = events_for(client, child)
    setup = next(e for e in events if e['kind'] == 'egg_setup')
    ready = next(e for e in events if e['kind'] == 'offspring_ready')
    assert setup['due'] == '2026-09-13T10:15' and ready['due'] == before['at']
    assert client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'cold', 'at': '2026-09-08T10:00',
    }).status_code == 200
    after = current(client, source)['eclosion_estimate']
    assert after['at'] == '2026-09-14T10:00' and after['basis'] == 'estimated'
    assert current(client, child)['source_eclosion_estimate'] == after
    changed = events_for(client, child)
    assert next(e for e in changed if e['id'] == ready['id'])['due'] == after['at']
    assert next(e for e in changed if e['id'] == setup['id'])['due'] == setup['due']


def test_observed_source_eclosion_replaces_forecast_without_changing_selected_start(client):
    source = create(client, purpose='stock', genotype='w')
    child = derive(client, source, initial_status='planned', setup_date='2026-09-12', setup_time='10:15').json()
    client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'eclosion', 'at': '2026-09-09T11:25',
    })
    estimate = current(client, child)['source_eclosion_estimate']
    assert estimate['basis'] == 'observed' and estimate['at'] == '2026-09-09T11:25'
    assert current(client, child)['setup_time'] == '10:15'


def test_date_only_source_reminder_uses_source_work_window_until_eclosion_is_observed(client):
    source = create(client, purpose='stock', genotype='w', setup_time=None)
    estimate = current(client, source)['eclosion_estimate']
    assert estimate['date_only'] is True and estimate['at'][:10] == '2026-09-11'
    child = derive(client, source, initial_status='planned', setup_date='2026-09-12').json()
    assert current(client, child)['source_eclosion_estimate']['date_only'] is True
    ready = next(e for e in events_for(client, child) if e['kind'] == 'offspring_ready')
    assert ready['due'] == '2026-09-11T09:00'

    changed_template = {**source['template'], 'windows': [['10:30', '11:30'], ['15:00', '15:30'], ['19:00', '21:00']]}
    response = client.put(f"/api/containers/{source['id']}", json=edit_body(source, template=changed_template))
    assert response.status_code == 200, response.text
    shifted = next(e for e in events_for(client, child) if e['id'] == ready['id'])
    assert shifted['due'] == '2026-09-11T10:30' and shifted['status'] == 'pending'
    assert current(client, child)['setup_time'] == '13:00'

    assert client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'eclosion', 'at': '2026-09-09T12:25',
    }).status_code == 200
    observed = current(client, child)['source_eclosion_estimate']
    assert observed['date_only'] is False and observed['basis'] == 'observed'
    assert observed['at'] == '2026-09-09T12:25'
    assert next(e for e in events_for(client, child) if e['id'] == ready['id'])['status'] == 'cancelled'


def test_planned_egg_setup_waits_for_actual_start_even_after_time_passes(client, monkeypatch):
    source = create(client, purpose='stock', genotype='w')
    child = derive(client, source, initial_status='planned', setup_date='2026-09-11', setup_time='10:15').json()
    original_setup = next(e for e in events_for(client, child) if e['kind'] == 'egg_setup')
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 12, 14))
    pending = current(client, child)
    assert pending['status'] == 'planned' and pending['setup_time'] == '10:15'
    assert next(e for e in events_for(client, child) if e['id'] == original_setup['id'])['status'] == 'pending'
    batch_payload = {'label': 'Actual laying window', 'genotype': 'w', 'lay_start': '2026-09-12T12:35', 'lay_end': '2026-09-12T13:35'}
    assert client.post(f"/api/containers/{child['id']}/egg-batches", json=batch_payload).status_code == 409
    response = client.post(f"/api/containers/{child['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-12T12:35', 'event_id': original_setup['id'],
    })
    assert response.status_code == 200, response.text
    started = current(client, child)
    assert started['status'] == 'active'
    assert (started['setup_date'], started['setup_time']) == ('2026-09-12', '12:35')
    assert not any(e['status'] == 'pending' for e in events_for(client, child))
    assert current(client, source)['parents'] == 'present'
    assert client.post(f"/api/containers/{child['id']}/egg-batches", json=batch_payload).status_code == 200


def test_planned_source_only_supplies_a_plan_until_source_is_actually_started(client, monkeypatch):
    source = create(client, purpose='stock', genotype='w', initial_status='planned', setup_date='2026-09-10')
    assert derive(client, source, initial_status='active').status_code == 409
    assert derive(client, source, adult_source='parents', initial_status='planned', setup_date='2026-09-22').status_code == 409
    response = derive(client, source, initial_status='planned', setup_date='2026-09-22', setup_time='10:00')
    assert response.status_code == 200, response.text
    child = response.json()
    assert current(client, child)['source_eclosion_estimate']['source_planned'] is True
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 23, 14))
    assert client.post(f"/api/containers/{child['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-23T10:00',
    }).status_code == 409
    assert client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-12T11:00',
    }).status_code == 200
    assert current(client, child)['source_eclosion_estimate']['at'] == '2026-09-22T11:00'
    assert current(client, child)['source_eclosion_estimate']['source_planned'] is False
    before = snapshot(client)
    assert client.post(f"/api/containers/{child['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-11T11:00',
    }).status_code == 422
    assert snapshot(client) == before
    assert client.post(f"/api/containers/{child['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-23T10:00',
    }).status_code == 200


def test_standalone_egg_container_uses_single_genotype_and_required_time(client):
    payload = {'kind': 'egg_laying', 'purpose': 'egg_laying', 'genotype': 'w1118',
               'setup_date': '2026-09-09', 'setup_time': '12:34'}
    response = client.post('/api/containers', json=payload)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['genotype'] == 'w1118' and child['setup_time'] == '12:34'
    for change in ({'setup_time': None}, {'setup_time': ''}, {'genotype': ''}):
        assert client.post('/api/containers', json=payload | change).status_code == 422
    updated = client.put(f"/api/containers/{child['id']}", json=edit_body(child, genotype='Updated known line'))
    assert updated.status_code == 200, updated.text
    assert updated.json()['genotype'] == 'Updated known line'
    assert client.put(f"/api/containers/{child['id']}", json=edit_body(child, genotype=' ')).status_code == 422


def test_legacy_egg_migration_preserves_facts_and_requires_unknown_data_review(client):
    source = create(client, parents='transferred')
    same = create(client, kind='egg_laying', purpose='egg_laying', genotype='w')
    mixed = create(client, kind='egg_laying', purpose='egg_laying', genotype='w')
    with module.database() as db:
        same.update(genotype='', female_genotype='w1118', male_genotype='w1118',
                    source_id=source['id'], source_relation='egg_laying_transfer')
        mixed.update(genotype='', female_genotype='nub-GAL4/CyO', male_genotype='UAS-X/TM6B', setup_time=None)
        for old in (same, mixed):
            old.pop('genotype_review_required', None)
            old.pop('setup_time_review_required', None)
            module.save_container(db, old)
        before = {table: [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                  for table in ('logs', 'events', 'temperatures', 'egg_batches')}
        db.execute("DELETE FROM meta WHERE key='known_egg_adults_v1'")
    module.init_db()
    with module.database() as db:
        migrated_same = module.get_container(db, same['id'])
        migrated_mixed = module.get_container(db, mixed['id'])
        assert migrated_same['genotype'] == 'w1118' and not migrated_same['genotype_review_required']
        assert migrated_same['adult_source'] == 'parents'
        assert migrated_mixed['genotype'] == '' and migrated_mixed['genotype_review_required']
        assert migrated_mixed['setup_time'] is None and migrated_mixed['setup_time_review_required']
        assert migrated_mixed['female_genotype'] == mixed['female_genotype']
        assert module.get_container(db, source['id']) == source
        for table, rows in before.items():
            assert [tuple(r) for r in db.execute(f'SELECT * FROM {table} ORDER BY id')] == rows
        first_dump = list(db.iterdump())
    module.init_db()
    with module.database() as db:
        assert list(db.iterdump()) == first_dump
    batch_payload = {'label': 'New laying window', 'genotype': 'w', 'lay_start': '2026-09-09T10:00', 'lay_end': '2026-09-09T12:00'}
    assert client.post(f"/api/containers/{mixed['id']}/egg-batches", json=batch_payload).status_code == 409
    response = client.put(f"/api/containers/{mixed['id']}", json=edit_body(
        migrated_mixed, genotype='Confirmed actual adults', setup_date='2026-09-01', setup_time='08:45'))
    assert response.status_code == 200, response.text
    reviewed = response.json()
    assert reviewed['genotype'] == 'Confirmed actual adults' and reviewed['setup_time'] == '08:45'
    assert not reviewed['genotype_review_required'] and not reviewed['setup_time_review_required']
    assert client.post(f"/api/containers/{mixed['id']}/egg-batches", json=batch_payload).status_code == 200


def test_inherited_source_connects_batch_dish_and_hourly_time_flow(client, monkeypatch):
    source = create(client, purpose='stock', genotype='w')
    child = derive(client, source, setup_time='09:00').json()
    response = client.post(f"/api/containers/{child['id']}/egg-batches", json={
        'label': 'Morning eggs', 'genotype': 'w', 'lay_start': '2026-09-09T09:00', 'lay_end': '2026-09-09T13:00',
    })
    assert response.status_code == 200, response.text
    batch = response.json()
    assert client.post(f"/api/egg-batches/{batch['id']}/actions", json={
        'action': 'collect', 'at': '2026-09-09T13:30',
    }).status_code == 200
    dish = create(client, kind='petri_dish', purpose='dissection', genotype='w', setup_date='2026-09-09',
                  setup_time='14:00', egg_batch_id=batch['id'],
                  incubation={'lay_start': batch['lay_start'], 'lay_end': batch['lay_end']})
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 10, 10))
    dish_state = current(client, dish)
    assert dish_state['egg_age_hours'] == [21, 25]
    assert dish_state['source_id'] == child['id']
    assert dish_state['incubation_window']['start'] == '2026-09-10T09:00'
    assert current(client, child)['source_id'] == source['id']


@pytest.mark.parametrize('override, expected', [(None, 18), (25, 25)])
def test_planned_temperature_inheritance_uses_actual_start_not_plan_or_latest_temperature(client, monkeypatch, override, expected):
    source = create(client, purpose='stock', genotype='w')
    before_logs = current(client, source)['logs']
    response = derive(client, source, initial_status='planned', setup_date='2026-09-11',
                      setup_time='10:00', initial_temperature=override)
    assert response.status_code == 200, response.text
    child = response.json()
    assert current(client, source)['logs'] == before_logs
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 13, 14))
    for action, at in [('cold', '2026-09-10T10:00'), ('warm', '2026-09-12T10:00')]:
        assert client.post(f"/api/containers/{source['id']}/actions", json={'action': action, 'at': at}).status_code == 200
    response = client.post(f"/api/containers/{child['id']}/actions", json={
        'action': 'activate', 'at': '2026-09-11T12:45',
    })
    assert response.status_code == 200, response.text
    assert response.json()['initial_temperature'] == expected
    assert current(client, source)['parents'] == 'present'


def test_observed_eclosion_cancels_pending_ready_check_but_preserves_completed_check(client):
    source = create(client, purpose='stock', genotype='w')
    first = derive(client, source, initial_status='planned', setup_date='2026-09-12').json()
    second = derive(client, source, initial_status='planned', setup_date='2026-09-12').json()
    pending = next(e for e in events_for(client, first) if e['kind'] == 'offspring_ready')
    completed = next(e for e in events_for(client, second) if e['kind'] == 'offspring_ready')
    assert client.patch(f"/api/events/{completed['id']}", json={'status': 'done'}).status_code == 200
    assert client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'eclosion', 'at': '2026-09-09T12:00',
    }).status_code == 200
    assert next(e for e in events_for(client, first) if e['id'] == pending['id'])['status'] == 'cancelled'
    assert next(e for e in events_for(client, second) if e['id'] == completed['id'])['status'] == 'done'
    assert current(client, first)['status'] == current(client, second)['status'] == 'planned'


def test_setup_reminder_cannot_be_marked_done_without_recording_actual_start(client):
    source = create(client, purpose='stock', genotype='w')
    child = derive(client, source, initial_status='planned', setup_date='2026-09-12').json()
    setup = next(e for e in events_for(client, child) if e['kind'] == 'egg_setup')
    before = snapshot(client)
    response = client.patch(f"/api/events/{setup['id']}", json={'status': 'done'})
    assert response.status_code == 409 and response.json()['detail'] == 'egg_setup_activation_required'
    assert snapshot(client) == before


def test_legacy_time_correction_cannot_move_start_after_existing_egg_window(client):
    egg = create(client, kind='egg_laying', purpose='egg_laying', genotype='w',
                 setup_date='2026-09-08', setup_time='08:00')
    assert client.post(f"/api/containers/{egg['id']}/egg-batches", json={
        'label': 'Already recorded eggs', 'genotype': 'w',
        'lay_start': '2026-09-08T09:00', 'lay_end': '2026-09-08T11:00',
    }).status_code == 200
    with module.database() as db:
        egg.update(setup_time=None, setup_time_review_required=True)
        module.save_container(db, egg)
    before = snapshot(client)
    response = client.put(f"/api/containers/{egg['id']}", json=edit_body(
        egg, setup_date='2026-09-08', setup_time='10:00'))
    assert response.status_code == 422 and response.json()['detail'] == 'egg_setup_after_recorded_activity'
    assert snapshot(client) == before
