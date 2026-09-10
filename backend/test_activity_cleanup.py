"""Recorded-operation correction exercises isolated databases and their backups."""
import json
import sqlite3

import pytest
from fastapi import HTTPException

from backend import app as module
from backend.test_app import client, create, snapshot
from backend.test_eggs import batch, collect, dish, laying


@pytest.fixture(autouse=True)
def isolated_backup_root(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)


def container(client, cid):
    return next(item for item in snapshot(client)['containers'] if item['id'] == cid)


def events(client, cid):
    return {item['id']: item for item in snapshot(client)['events'] if item['container_id'] == cid}


def record(client, culture, action, at='2026-09-08T10:00', **extra):
    before_ids = {item['id'] for item in container(client, culture['id'])['logs']}
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': action, 'at': at, **extra,
    })
    assert response.status_code == 200, response.text
    return next(item for item in container(client, culture['id'])['logs']
                if item['action'] == action and item['id'] not in before_ids)


def preview(client, cid, lid):
    response = client.get(f'/api/containers/{cid}/activities/{lid}/delete-preview')
    assert response.status_code == 200, response.text
    return response.json()


def delete(client, cid, lid, shown=None, **extra):
    shown = shown if shown is not None else preview(client, cid, lid)
    return client.request('DELETE', f'/api/containers/{cid}/activities/{lid}', json={
        'fingerprint': shown['fingerprint'], **extra,
    })


def database_dump():
    with module.database() as db:
        return list(db.iterdump())


def make_legacy(lid):
    """Represent a record made before operation snapshots were introduced."""
    with module.database() as db:
        db.execute('DELETE FROM meta WHERE key=?', ('activity_undo:' + lid,))


def test_temperature_undo_restores_forecast_and_keeps_pinned_work(client):
    c = create(client)
    original_events = events(client, c['id'])
    collection = next(item for item in original_events.values() if item['kind'] == 'collect')
    response = client.patch(f"/api/events/{collection['id']}", json={
        'due': '2026-09-16T09:00', 'end': '2026-09-16T11:00',
    })
    assert response.status_code == 200, response.text
    before = events(client, c['id'])
    activity = record(client, c, 'cold', at='2026-09-03T10:00')
    changed = container(client, c['id'])
    assert changed['temperature'] == 18
    assert any(events(client, c['id'])[eid]['due'] != item['due'] for eid, item in before.items())

    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    restored = container(client, c['id'])
    assert restored['temperature'] == 25
    assert all(item['id'] != activity['id'] for item in restored['logs'])
    assert events(client, c['id']) == before
    with module.database() as db:
        assert module.temperatures_of(db, c['id']) == []


def test_warm_undo_preserves_earlier_temperature_history(client):
    c = create(client)
    cold = record(client, c, 'cold', at='2026-09-03T10:00')
    before = events(client, c['id'])
    warm = record(client, c, 'warm', at='2026-09-05T10:00')
    response = delete(client, c['id'], warm['id'])
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['temperature'] == 18 and any(item['id'] == cold['id'] for item in after['logs'])
    assert events(client, c['id']) == before
    with module.database() as db:
        temperatures = module.temperatures_of(db, c['id'])
    assert len(temperatures) == 1 and temperatures[0]['temperature'] == 18


def test_remove_undo_restores_parents_and_cancelled_transfer(client):
    c = create(client)
    before = events(client, c['id'])
    activity = record(client, c, 'remove', at='2026-09-03T10:00')
    assert container(client, c['id'])['parents'] == 'removed'
    assert next(item for item in events(client, c['id']).values() if item['kind'] == 'transfer')['status'] == 'cancelled'
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['parents'] == 'present'
    assert events(client, c['id']) == before


def test_clear_undo_restores_previous_clear_clock_and_custom_parent_state(client):
    c = create(client, parents='transferred')
    first = record(client, c, 'clear', at='2026-09-07T09:00')
    second = record(client, c, 'clear', at='2026-09-08T09:00')
    assert container(client, c['id'])['clock']['last_clear'] == second['at']
    response = delete(client, c['id'], second['id'])
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['parents'] == 'transferred'
    assert after['clock']['last_clear'] == first['at']
    response = delete(client, c['id'], first['id'])
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['clock']['state'] == 'unknown'


@pytest.mark.parametrize('delete_member', ['collect', 'clear'])
def test_collect_and_clear_are_undone_together_and_reopen_only_exact_task(client, delete_member):
    c = create(client)
    before = events(client, c['id'])
    collection = next(item for item in before.values() if item['kind'] == 'collect')
    activity = record(client, c, 'collect', event_id=collection['id'], cleared=True)
    paired = next(item for item in container(client, c['id'])['logs'] if item['action'] == 'clear')
    target = activity if delete_member == 'collect' else paired
    shown = preview(client, c['id'], target['id'])
    assert {item['id'] for item in shown['related_activities']} | {target['id']} >= {activity['id'], paired['id']}
    response = delete(client, c['id'], target['id'], shown)
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['parents'] == 'present' and after['clock']['state'] == 'unknown'
    assert {item['action'] for item in after['logs']} == {'created'}
    assert events(client, c['id']) == before


def test_undo_collection_keeps_existing_reschedule_and_other_completed_window(client):
    c = create(client)
    collection = [item for item in events(client, c['id']).values() if item['kind'] == 'collect']
    response = client.patch(f"/api/events/{collection[0]['id']}", json={'status': 'done'})
    assert response.status_code == 200, response.text
    response = client.patch(f"/api/events/{collection[1]['id']}", json={
        'due': '2026-09-08T09:00', 'end': '2026-09-08T11:00',
    })
    assert response.status_code == 200, response.text
    before = events(client, c['id'])
    activity = record(client, c, 'collect', event_id=collection[1]['id'])
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    after = events(client, c['id'])
    assert after == before
    assert after[collection[0]['id']]['status'] == 'done'
    assert after[collection[1]['id']]['pinned'] and after[collection[1]['id']]['due'] == '2026-09-08T09:00'
    assert len([item for item in after.values() if item['kind'] == 'collect']) == 3


@pytest.mark.parametrize(('initial', 'operation'), [('larvae', 'pupae'), ('pupae', 'eclosion')])
def test_observation_undo_restores_custom_initial_stage_without_inventing_unobserved(client, initial, operation):
    c = create(client, stage=initial)
    activity = record(client, c, operation)
    assert container(client, c['id'])['stage'] == operation
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['stage'] == initial
    assert not after.get('first_eclosion_at')


def test_first_instar_undo_restores_hourly_stage_and_same_reminder(client):
    c = dish(client)
    before = events(client, c['id'])
    activity = record(client, c, 'first_instar', at='2026-09-09T10:00')
    assert container(client, c['id'])['stage'] == 'first_instar'
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['stage'] == 'unobserved'
    assert events(client, c['id']) == before


def test_later_operation_blocks_earlier_undo_until_dependency_is_removed(client):
    c = create(client)
    first = record(client, c, 'larvae', at='2026-09-06T09:00')
    later = record(client, c, 'pupae', at='2026-09-07T09:00')
    shown = preview(client, c['id'], first['id'])
    assert not shown['can_delete'] and shown['blockers']
    before = database_dump()
    response = delete(client, c['id'], first['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before
    assert delete(client, c['id'], later['id']).status_code == 200
    assert delete(client, c['id'], first['id']).status_code == 200
    assert container(client, c['id'])['stage'] == 'unobserved'


def test_later_reminder_edit_is_never_overwritten_by_undo(client):
    c = create(client)
    task = next(item for item in events(client, c['id']).values() if item['kind'] == 'collect')
    activity = record(client, c, 'collect', event_id=task['id'])
    response = client.patch(f"/api/events/{task['id']}", json={
        'due': '2026-09-17T13:00', 'end': '2026-09-17T14:00',
    })
    assert response.status_code == 200, response.text
    shown = preview(client, c['id'], activity['id'])
    assert not shown['can_delete'] and shown['blockers']
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before
    assert events(client, c['id'])[task['id']]['due'] == '2026-09-17T13:00'


@pytest.mark.parametrize('action', ['complete', 'discard'])
def test_closing_undo_restores_exact_statuses_and_planned_egg_batches(client, action):
    c = laying(client)
    eggs = batch(client, c)
    custom = client.post('/api/events', json={
        'container_id': c['id'], 'title': 'Inspect food',
        'due': '2026-09-09T10:00', 'end': '2026-09-09T11:00',
    }).json()
    assert client.patch(f"/api/events/{custom['id']}", json={'status': 'disabled'}).status_code == 200
    before = events(client, c['id'])
    activity = record(client, c, action)
    with module.database() as db:
        assert module.get_egg_batch(db, eggs['id'])['status'] == 'cancelled'
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['status'] == 'active'
    assert events(client, c['id']) == before
    with module.database() as db:
        assert module.get_egg_batch(db, eggs['id'])['status'] == 'planned'


def test_legacy_discard_reopens_only_reminders_cancelled_by_closure(client):
    c = create(client)
    tasks = list(events(client, c['id']).values())
    assert client.patch(f"/api/events/{tasks[0]['id']}", json={'status': 'disabled'}).status_code == 200
    assert client.patch(f"/api/events/{tasks[1]['id']}", json={'status': 'done'}).status_code == 200
    before = events(client, c['id'])
    activity = record(client, c, 'discard')
    make_legacy(activity['id'])
    shown = preview(client, c['id'], activity['id'])
    assert shown['legacy'] and shown['can_delete']
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['status'] == 'active'
    assert events(client, c['id']) == before


@pytest.mark.parametrize('reopen', [False, True])
def test_legacy_third_instar_asks_which_completed_reminder_to_reopen(client, reopen):
    c = create(client, purpose='larvae', genotype='w1118', stage='larvae')
    task = next(item for item in events(client, c['id']).values() if item['kind'] == 'third_instar')
    activity = record(client, c, 'third_instar', event_id=task['id'])
    make_legacy(activity['id'])
    shown = preview(client, c['id'], activity['id'])
    assert shown['legacy']
    assert task['id'] in {item['id'] for item in shown['reminders']}
    response = delete(client, c['id'], activity['id'], shown,
                      reopen_event_ids=[task['id']] if reopen else [])
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['stage'] == 'larvae' and after['parents'] == 'present'
    assert events(client, c['id'])[task['id']]['status'] == ('pending' if reopen else 'done')


def test_legacy_stage_requires_explicit_correction_not_a_guessed_baseline(client):
    c = create(client, stage='pupae')
    activity = record(client, c, 'eclosion')
    make_legacy(activity['id'])
    shown = preview(client, c['id'], activity['id'])
    assert shown['legacy'] and any(item['field'] == 'stage' for item in shown['corrections'])
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 422
    assert database_dump() == before
    response = delete(client, c['id'], activity['id'], shown, corrections={'stage': 'pupae'})
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['stage'] == 'pupae'


def test_legacy_clear_requires_parent_correction_and_removes_clear_clock(client):
    c = create(client)
    activity = record(client, c, 'clear')
    make_legacy(activity['id'])
    shown = preview(client, c['id'], activity['id'])
    assert any(item['field'] == 'parents' for item in shown['corrections'])
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 422
    assert database_dump() == before
    response = delete(client, c['id'], activity['id'], shown, corrections={'parents': 'present'})
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['parents'] == 'present' and after['clock']['state'] == 'unknown'


def test_activation_undo_restores_planned_setup_without_resetting_source_identity(client):
    c = create(client, setup_date='2026-09-12', setup_time='11:00')
    activity = record(client, c, 'activate')
    assert container(client, c['id'])['status'] == 'active'
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert (after['status'], after['setup_date'], after['setup_time']) == ('planned', '2026-09-12', '11:00')
    assert (after['cohort_id'], after['source_id']) == (c['cohort_id'], c['source_id'])


def test_transfer_activity_cannot_be_removed_while_linked_container_exists(client):
    source = create(client)
    response = client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'transfer', 'purpose': 'cross',
        'female_genotype': source['female_genotype'], 'male_genotype': source['male_genotype'],
        'setup_date': '2026-09-03', 'setup_time': '11:00',
    })
    assert response.status_code == 200, response.text
    activity = next(item for item in container(client, source['id'])['logs'] if item['action'] == 'transfer')
    shown = preview(client, source['id'], activity['id'])
    assert not shown['can_delete'] and shown['blockers']
    before = database_dump()
    response = delete(client, source['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before


def test_undo_snapshot_survives_database_reinitialization(client):
    c = create(client, stage='pupae', parents='transferred')
    activity = record(client, c, 'eclosion')
    module.init_db()
    shown = preview(client, c['id'], activity['id'])
    assert not shown['legacy'] and shown['can_delete']
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 200, response.text
    after = container(client, c['id'])
    assert after['stage'] == 'pupae' and after['parents'] == 'transferred'


def test_preview_is_read_only_and_stale_confirmation_does_not_write(client, tmp_path):
    c = create(client)
    activity = record(client, c, 'larvae')
    before = database_dump()
    shown = preview(client, c['id'], activity['id'])
    assert shown['can_delete'] and database_dump() == before
    with module.database() as db:
        db.execute('UPDATE logs SET notes=? WHERE id=?', ('Corrected note after preview', activity['id']))
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()


def test_undo_preserves_other_container_and_backup_restores_all_original_records(client, tmp_path):
    c, other = create(client), create(client, kind='bottle', label='Untouched culture')
    activity = record(client, c, 'remove')
    unaffected_container, unaffected_events = container(client, other['id']), events(client, other['id'])
    before = database_dump()
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, other['id']) == unaffected_container
    assert events(client, other['id']) == unaffected_events
    path = tmp_path / 'backups' / response.json()['backup']
    assert path.is_file()
    with sqlite3.connect(path) as restored:
        assert list(restored.iterdump()) == before
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert restored.execute('SELECT id FROM logs WHERE id=?', (activity['id'],)).fetchone()


def test_backup_failure_keeps_activity_and_all_effects(client, monkeypatch):
    from backend import activity_cleanup as cleanup
    c = create(client)
    activity = record(client, c, 'remove')
    before = database_dump()

    def fail_backup(*_):
        raise HTTPException(500, 'deletion_backup_failed')

    monkeypatch.setattr(cleanup, '_backup_before_delete', fail_backup)
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 500
    assert database_dump() == before


def test_created_activity_cannot_be_removed_as_if_it_were_an_observation(client):
    c = create(client)
    activity = next(item for item in container(client, c['id'])['logs'] if item['action'] == 'created')
    shown = preview(client, c['id'], activity['id'])
    assert not shown['can_delete'] and shown['blockers']
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before


def test_activity_id_cannot_be_deleted_through_another_container(client):
    c, other = create(client), create(client)
    activity = record(client, c, 'tissue')
    before = database_dump()
    response = client.get(f"/api/containers/{other['id']}/activities/{activity['id']}/delete-preview")
    assert response.status_code == 404
    response = client.request('DELETE', f"/api/containers/{other['id']}/activities/{activity['id']}",
                              json={'fingerprint': 'anything'})
    assert response.status_code == 404
    assert database_dump() == before


@pytest.mark.parametrize('operation', ['window', 'collect', 'use', 'cancel'])
def test_egg_activity_undo_restores_batch_and_exact_reminders(client, operation):
    c = laying(client)
    if operation == 'window':
        before_batches = snapshot(client)['egg_batches']
        before_events = events(client, c['id'])
        eggs = batch(client, c)
    else:
        eggs = batch(client, c)
        if operation == 'use':
            collect(client, eggs)
        before_batches = snapshot(client)['egg_batches']
        before_events = events(client, c['id'])
        response = client.post(f"/api/egg-batches/{eggs['id']}/actions", json={
            'action': operation, 'at': '2026-09-08T14:00',
            'purpose': 'imaging', 'notes': 'Mistaken operation',
        })
        assert response.status_code == 200, response.text
    activity = next(item for item in container(client, c['id'])['logs'] if item['action'] == 'egg_' + operation)
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert snapshot(client)['egg_batches'] == before_batches
    assert events(client, c['id']) == before_events


@pytest.mark.parametrize('operation', ['window', 'collect'])
def test_existing_dish_blocks_undo_of_the_eggs_it_uses(client, operation):
    c = laying(client)
    eggs = batch(client, c)
    collect(client, eggs)
    used_in = dish(client, eggs)
    activity = next(item for item in container(client, c['id'])['logs'] if item['action'] == 'egg_' + operation)
    shown = preview(client, c['id'], activity['id'])
    assert not shown['can_delete'] and shown['blockers']
    before = database_dump()
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before
    assert container(client, used_in['id'])['egg_batch_id'] == eggs['id']


def test_transfer_can_be_undone_after_its_mistaken_child_is_permanently_removed(client):
    source = create(client)
    before_events = events(client, source['id'])
    response = client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'transfer', 'purpose': 'cross',
        'female_genotype': source['female_genotype'], 'male_genotype': source['male_genotype'],
        'setup_date': '2026-09-03', 'setup_time': '11:00',
    })
    assert response.status_code == 200, response.text
    child = response.json()
    shown = client.get(f"/api/containers/{child['id']}/delete-preview").json()
    response = client.request('DELETE', f"/api/containers/{child['id']}", json={
        'confirmation_label': child['label'], 'fingerprint': shown['fingerprint'],
    })
    assert response.status_code == 200, response.text
    activity = next(item for item in container(client, source['id'])['logs'] if item['action'] == 'transfer')
    response = delete(client, source['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, source['id'])['parents'] == 'present'
    assert events(client, source['id']) == before_events


@pytest.mark.parametrize('tamper', ['table', 'owner'])
def test_invalid_journal_cannot_modify_tables_or_another_containers_records(client, tamper):
    c, other = create(client), create(client)
    task = next(item for item in events(client, c['id']).values() if item['kind'] == 'collect')
    activity = record(client, c, 'collect', event_id=task['id'])
    with module.database() as db:
        key = 'activity_undo:' + activity['id']
        journal = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        change = next(item for item in journal['changes'] if item['table'] == 'events')
        if tamper == 'table':
            change['table'] = 'meta'
        else:
            for row in (change['before'], change['after']):
                row['container_id'] = other['id']
                payload = json.loads(row['payload'])
                payload['container_id'] = other['id']
                row['payload'] = json.dumps(payload)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(journal), key))
    before = database_dump()
    shown = preview(client, c['id'], activity['id'])
    assert not shown['can_delete'] and 'invalid_journal' in shown['blockers']
    response = delete(client, c['id'], activity['id'], shown)
    assert response.status_code == 409
    assert database_dump() == before


@pytest.mark.parametrize('tamper', ['stage', 'rule_key', 'malformed_primary'])
def test_undo_rejects_invalid_restored_payloads_before_any_write(client, tamper):
    c = create(client)
    activity = record(client, c, 'remove')
    with module.database() as db:
        key = 'activity_undo:' + activity['id']
        journal = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        if tamper == 'malformed_primary':
            value = '{not json'
        else:
            table = 'containers' if tamper == 'stage' else 'events'
            change = next(item for item in journal['changes'] if item['table'] == table)
            previous = json.loads(change['before']['payload'])
            previous['stage' if tamper == 'stage' else 'rule_key'] = 'invalid-restored-value'
            change['before']['payload'] = json.dumps(previous)
            value = json.dumps(journal)
        db.execute('UPDATE meta SET value=? WHERE key=?', (value, key))
    before = database_dump()
    shown = preview(client, c['id'], activity['id'])
    assert not shown['can_delete'] and 'invalid_journal' in shown['blockers']
    assert delete(client, c['id'], activity['id'], shown).status_code == 409
    assert database_dump() == before


def test_workspace_import_preserves_operation_undo(client, tmp_path):
    from backend.workspace_restore import WorkspaceImporter, RestoreInput

    c = create(client, stage='pupae')
    activity = record(client, c, 'larvae')
    exported = client.get('/api/backup')
    assert exported.status_code == 200
    assert delete(client, c['id'], activity['id']).status_code == 200
    importer = WorkspaceImporter(module, backup_dir=tmp_path / 'restore-backups')
    try:
        shown = importer.preview(exported.content)
        importer.restore(RestoreInput(token=shown['token'], confirmation='RESTORE',
            expected_current_fingerprint=shown['current_fingerprint']))
    finally:
        importer.close()
    assert container(client, c['id'])['stage'] == 'larvae'
    response = delete(client, c['id'], activity['id'])
    assert response.status_code == 200, response.text
    assert container(client, c['id'])['stage'] == 'pupae'
