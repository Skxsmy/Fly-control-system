"""Injection lineage, correction and backup tests use isolated workspaces only."""
import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime

import pytest
from fastapi import HTTPException

from backend import activity_cleanup, container_cleanup, workspace_restore
from backend import app as module
from backend.test_app import client, create


@pytest.fixture(autouse=True)
def isolated_backups(tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)


def injection(role, phase, **changes):
    return {'role': role, 'phase': phase, 'initiated_at': '2026-09-02T10:00',
            'started_at': None, 'female_count': None, 'male_count': None,
            'female_target': 200, 'male_target': 50, 'cycle': 0,
            'renewed_at': None, 'next_renew_at': None, 'finished_at': None,
            'transferred_at': None, **changes}


def child(db, source, kind, data):
    value = deepcopy(source)
    value.update(id=module.uid(), label=container_cleanup.next_container_label(
        db, kind, namespace='injection' if kind == 'bottle' else None),
        kind=kind, purpose='injection', source_id=source['id'],
        source_relation='injection', cohort_id=module.uid(), status='planned',
        setup_date='2026-09-11', setup_time='10:00', injection=data,
        workflow=None, parents='present', stage='unobserved', transfer_index=0,
        initial_temperature=25, temperature_policy='forbidden')
    if data.get('started_at'):
        value['setup_date'], value['setup_time'] = data['started_at'].split('T')
    db.execute('INSERT INTO containers VALUES(?,?,?)', (value['id'], value['label'], module.dump(value)))
    module.log(db, value['id'], 'created', '2026-09-02T10:00')
    return value


def begin(client):
    source = create(client, kind='bottle', purpose='stock', genotype='w1118')
    with module.database() as db:
        before = activity_cleanup.snapshot(db)
        source['injection'] = injection('source', 'collecting')
        source['temperature_policy'] = 'forbidden'
        module.save_container(db, source)
        destination = child(db, source, 'bottle', injection('conditioning', 'awaiting_flies'))
        module.log(db, source['id'], 'injection_preparation', '2026-09-02T10:00')
        activity_cleanup.record(db, before, source['id'])
        log_id = db.execute("SELECT id FROM logs WHERE action='injection_preparation'").fetchone()[0]
    return source, destination, log_id


def collect(source, destination):
    with module.database() as db:
        before = activity_cleanup.snapshot(db)
        anchor = '2026-09-08T10:00'
        source['injection'].update(phase='finished', started_at=anchor, finished_at=anchor,
                                   female_count=200, male_count=50)
        destination.update(status='active', setup_date='2026-09-08', setup_time='10:00')
        destination['injection'].update(phase='conditioning', started_at=anchor, female_count=200, male_count=50)
        module.save_container(db, source)
        module.save_container(db, destination)
        module.log(db, source['id'], 'injection_collect', anchor)
        module.log(db, destination['id'], 'activate', anchor)
        activity_cleanup.record(db, before, source['id'])
        return db.execute("SELECT id FROM logs WHERE container_id=? AND action='injection_collect'", (source['id'],)).fetchone()[0]


def preview(client, cid, lid):
    response = client.get(f'/api/containers/{cid}/activities/{lid}/delete-preview')
    assert response.status_code == 200, response.text
    return response.json()


def undo(client, cid, lid):
    shown = preview(client, cid, lid)
    assert shown['can_delete'], shown
    response = client.request('DELETE', f'/api/containers/{cid}/activities/{lid}', json={'fingerprint': shown['fingerprint']})
    assert response.status_code == 200, response.text


def test_injection_labels_have_independent_namespaces(client):
    create(client, kind='bottle', purpose='stock', genotype='w1118')
    with module.database() as db:
        assert container_cleanup.next_container_label(db, 'bottle') == 'B0002'
        assert container_cleanup.next_container_label(db, 'bottle', 'injection') == 'IB0001'
        assert container_cleanup.next_container_label(db, 'cage') == 'C0001'
        with pytest.raises(ValueError):
            container_cleanup.next_container_label(db, 'vial', 'injection')


def test_preparation_undo_removes_untouched_planned_bottle(client):
    source, destination, lid = begin(client)
    undo(client, source['id'], lid)
    with module.database() as db:
        restored = module.get_container(db, source['id'])
        assert not restored.get('injection')
        assert not db.execute('SELECT 1 FROM containers WHERE id=?', (destination['id'],)).fetchone()
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
        assert container_cleanup.next_container_label(db, 'bottle', 'injection') == 'IB0001'


def test_preparation_with_later_child_work_preserves_record_only_option(client):
    source, destination, lid = begin(client)
    with module.database() as db:
        module.log(db, destination['id'], 'image', '2026-09-03T10:00', 'Later work')
    shown = preview(client, source['id'], lid)
    assert not shown['can_delete'] and shown['keep_later']['can_delete']
    response = client.request('DELETE', f"/api/containers/{source['id']}/activities/{lid}", json={
        'mode': 'keep_later', 'fingerprint': shown['keep_later']['fingerprint']})
    assert response.status_code == 200, response.text
    with module.database() as db:
        assert module.get_container(db, destination['id'])['source_id'] == source['id']


def test_collection_undo_restores_both_source_and_existing_destination(client):
    source, destination, _ = begin(client)
    lid = collect(source, destination)
    undo(client, source['id'], lid)
    with module.database() as db:
        assert module.get_container(db, source['id'])['injection']['phase'] == 'collecting'
        restored = module.get_container(db, destination['id'])
        assert restored['status'] == 'planned' and restored['injection']['started_at'] is None
        assert not db.execute("SELECT 1 FROM logs WHERE container_id=? AND action='activate'", (destination['id'],)).fetchone()


def test_collection_undo_cannot_orphan_subsequently_planned_cage(client):
    source, destination, _ = begin(client)
    lid = collect(source, destination)
    with module.database() as db:
        child(db, destination, 'cage', injection('cage', 'awaiting_transfer', started_at=destination['injection']['started_at']))
    shown = preview(client, source['id'], lid)
    assert not shown['can_delete'] and 'linked_container' in shown['blockers']
    assert shown['keep_later']['can_delete']


def test_transfer_undo_restores_bottle_and_cage_inherited_anchor(client):
    source, destination, _ = begin(client)
    collect(source, destination)
    with module.database() as db:
        cage = child(db, destination, 'cage', injection('cage', 'awaiting_transfer', started_at=destination['injection']['started_at']))
        before = activity_cleanup.snapshot(db)
        destination['status'] = 'discarded'
        destination['injection']['phase'] = 'finished'
        destination['injection']['finished_at'] = '2026-09-09T10:00'
        cage['status'] = 'active'
        cage['injection'].update(phase='renew', transferred_at='2026-09-09T10:00')
        module.save_container(db, destination)
        module.save_container(db, cage)
        module.log(db, destination['id'], 'injection_transfer', '2026-09-09T10:00')
        module.log(db, cage['id'], 'activate', '2026-09-09T10:00')
        activity_cleanup.record(db, before, destination['id'])
        lid = db.execute("SELECT id FROM logs WHERE container_id=? AND action='injection_transfer'", (destination['id'],)).fetchone()[0]
    undo(client, destination['id'], lid)
    with module.database() as db:
        assert module.get_container(db, destination['id'])['status'] == 'active'
        restored = module.get_container(db, cage['id'])
        assert restored['status'] == 'planned'
        assert restored['injection']['transferred_at'] is None
        assert restored['injection']['started_at'] == '2026-09-08T10:00'


def test_injection_backup_records_validate_and_keep_lineage(client):
    source, destination, _ = begin(client)
    collect(source, destination)
    with module.database() as db:
        cage = child(db, destination, 'cage', injection('cage', 'awaiting_transfer', started_at=destination['injection']['started_at']))
        rows = workspace_restore._read_rows(db)
    workspace_restore._validate_records(rows, module)
    assert json.loads(next(row['payload'] for row in rows['containers'] if row['id'] == cage['id']))['source_id'] == destination['id']


@pytest.mark.parametrize('correction', [
    {'source_id': 'missing'}, {'injection': {'role': 'cage', 'phase': 'invented'}},
    {'started_at': '2026-09-08T12:00'}, {'female_count': True},
])
def test_injection_restore_rejects_broken_link_or_metadata(client, correction):
    source, destination, _ = begin(client)
    collect(source, destination)
    with module.database() as db:
        rows = workspace_restore._read_rows(db)
    row = next(row for row in rows['containers'] if row['id'] == destination['id'])
    value = json.loads(row['payload'])
    if 'source_id' in correction or 'injection' in correction:
        value.update(correction)
    else:
        value['injection'].update(correction)
    row['payload'] = json.dumps(value)
    with pytest.raises((HTTPException, ValueError)):
        workspace_restore._validate_records(rows, module)


def test_permanent_deletion_keeps_injection_lineage_intact(client, tmp_path):
    source, destination, _ = begin(client)
    with module.database() as db:
        assert not container_cleanup.preview_container_deletion(db, source['id'])['can_delete']
        shown = container_cleanup.preview_container_deletion(db, destination['id'])
    with module.database() as db:
        container_cleanup.delete_container_permanently(db, destination['id'], shown['label'], shown['fingerprint'], tmp_path / 'backups')
    with module.database() as db:
        assert container_cleanup.preview_container_deletion(db, source['id'])['can_delete']
        workspace_restore._validate_records(workspace_restore._read_rows(db), module)


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_real_api_injection_chain_backup_and_transfer_undo(client, monkeypatch, tmp_path, kind):
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 16, 11))
    source = create(client, kind=kind, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-02T10:00', 'genotype': 'w1118'})
    assert response.status_code == 200, response.text
    bottle = response.json()['bottle']
    response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
        'action': 'injection_collect', 'at': '2026-09-11T10:00', 'female_count': 200, 'male_count': 50})
    assert response.status_code == 200, response.text
    state = client.get('/api/state').json()
    cage = next(c for c in state['containers'] if c['kind'] == 'cage')
    response = client.post(f"/api/containers/{bottle['id']}/injection-actions", json={
        'action': 'injection_transfer', 'at': '2026-09-15T10:00'})
    assert response.status_code == 200, response.text
    with module.database() as db:
        original = workspace_restore._read_rows(db)
        lid = db.execute("SELECT id FROM logs WHERE container_id=? AND action='injection_transfer'", (bottle['id'],)).fetchone()[0]
    backup = tmp_path / 'injection-roundtrip.db'
    with closing(sqlite3.connect(module.DB_PATH)) as source_db, closing(sqlite3.connect(backup)) as target:
        source_db.backup(target)
    assert workspace_restore.validate_snapshot(backup, module) == original
    undo(client, bottle['id'], lid)
    with module.database() as db:
        assert module.get_container(db, bottle['id'])['status'] == 'active'
        restored_cage = module.get_container(db, cage['id'])
        assert restored_cage['status'] == 'planned'
        assert restored_cage['setup_date'] == '2026-09-11'
        assert datetime.fromisoformat(restored_cage['injection']['started_at']) == datetime(2026, 9, 11, 10)
        workspace_restore._validate_records(workspace_restore._read_rows(db), module)


def test_real_api_preparation_undo_removes_planned_housing(client):
    source = create(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-02T10:00', 'genotype': 'w1118'})
    assert response.status_code == 200, response.text
    with module.database() as db:
        lid = db.execute("SELECT id FROM logs WHERE action='injection_preparation'").fetchone()[0]
    undo(client, source['id'], lid)
    state = client.get('/api/state').json()
    assert len(state['containers']) == 1
    assert not state['containers'][0].get('injection')
    assert any(e['kind'] == 'stock' and e['status'] == 'pending' for e in state['events'])


@pytest.mark.parametrize('owner_role', ['source', 'conditioning'])
@pytest.mark.parametrize('action', ['complete', 'discard'])
def test_closing_preparation_undo_reopens_only_planned_linked_housing(client, monkeypatch, owner_role, action):
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 16, 11))
    source = create(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-02T10:00', 'genotype': 'w1118'})
    assert response.status_code == 200, response.text
    owner, destination = source, response.json()['bottle']
    if owner_role == 'conditioning':
        response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
            'action': 'injection_collect', 'at': '2026-09-11T10:00', 'female_count': 200, 'male_count': 50})
        assert response.status_code == 200, response.text
        owner = response.json()['bottle']
        destination = next(c for c in client.get('/api/state').json()['containers'] if c['kind'] == 'cage')
    response = client.post(f"/api/containers/{owner['id']}/actions", json={'action': action, 'at': '2026-09-16T10:00'})
    assert response.status_code == 200, response.text
    with module.database() as db:
        assert module.get_container(db, destination['id'])['status'] == 'discarded'
        workspace_restore._validate_records(workspace_restore._read_rows(db), module)
        lid = db.execute('SELECT id FROM logs WHERE container_id=? AND action=?', (owner['id'], action)).fetchone()[0]
    undo(client, owner['id'], lid)
    with module.database() as db:
        assert module.get_container(db, owner['id'])['status'] == 'active'
        assert module.get_container(db, destination['id'])['status'] == 'planned'
        workspace_restore._validate_records(workspace_restore._read_rows(db), module)


@pytest.mark.parametrize('housing_role', ['conditioning', 'cage'])
def test_deleting_planned_housing_stops_related_pending_chain(client, monkeypatch, tmp_path, housing_role):
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 16, 11))
    source = create(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-02T10:00', 'genotype': 'w1118'})
    parent, housing = source, response.json()['bottle']
    if housing_role == 'cage':
        response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
            'action': 'injection_collect', 'at': '2026-09-11T10:00', 'female_count': 200, 'male_count': 50})
        assert response.status_code == 200, response.text
        parent = response.json()['bottle']
        housing = next(c for c in client.get('/api/state').json()['containers'] if c['kind'] == 'cage')
    with module.database() as db:
        shown = container_cleanup.preview_container_deletion(db, housing['id'])
        assert shown['effects'] == [{'kind': 'stop_injection_collection' if housing_role == 'conditioning' else 'stop_injection_conditioning',
                                     'container_id': parent['id'], 'label': parent['label']}]
    with module.database() as db:
        container_cleanup.delete_container_permanently(db, housing['id'], shown['label'], shown['fingerprint'], tmp_path / 'backups',
                                                       at='2026-09-16T11:00')
    state = client.get('/api/state').json()
    current = next(c for c in state['containers'] if c['id'] == parent['id'])
    assert current['status'] == 'active' and current['injection']['phase'] == 'finished'
    assert not any(c['id'] == housing['id'] for c in state['containers'])
    assert not any(e['container_id'] == parent['id'] and e['kind'] in ('stock', 'injection_collect', 'injection_transfer')
                   and e['status'] == 'pending' for e in state['events'])
    with module.database() as db:
        workspace_restore._validate_records(workspace_restore._read_rows(db), module)


def test_planned_housing_delete_preview_stales_when_related_parent_changes(client, tmp_path):
    source, housing, _ = begin(client)
    with module.database() as db:
        shown = container_cleanup.preview_container_deletion(db, housing['id'])
        source['notes'] = 'Updated source'
        module.save_container(db, source)
    with module.database() as db, pytest.raises(HTTPException, match='deletion_preview_changed'):
        container_cleanup.delete_container_permanently(db, housing['id'], shown['label'], shown['fingerprint'], tmp_path / 'backups')


def test_imported_injection_journal_cannot_rewrite_child_genotype(client):
    source, destination, _ = begin(client)
    lid = collect(source, destination)
    with module.database() as db:
        key = 'activity_undo:' + lid
        journal = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        changed = next(change for change in journal['changes'] if change['table'] == 'containers' and change['id'] == destination['id'])
        previous = json.loads(changed['before']['payload'])
        previous['genotype'] = 'Unrelated replacement'
        changed['before']['payload'] = json.dumps(previous)
        db.execute('UPDATE meta SET value=? WHERE key=?', (json.dumps(journal), key))
    shown = preview(client, source['id'], lid)
    assert not shown['can_delete'] and 'invalid_journal' in shown['blockers']
    assert shown['keep_later']['can_delete']
    with module.database() as db:
        assert module.get_container(db, destination['id'])['genotype'] == 'w1118'


def test_restore_accepts_warm_source_with_earlier_cold_history_but_rejects_cold_during_preparation(client):
    source = create(client, purpose='stock', genotype='w1118', initial_temperature=18)
    response = client.post(f"/api/containers/{source['id']}/actions", json={'action': 'warm', 'at': '2026-09-02T10:00'})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-03T10:00', 'genotype': 'w1118'})
    assert response.status_code == 200, response.text
    with module.database() as db:
        rows = workspace_restore._read_rows(db)
    workspace_restore._validate_records(rows, module)
    rows['temperatures'].append({'id': 'invalid-cooling', 'container_id': source['id'], 'at': '2026-09-04T10:00', 'temperature': 18})
    with pytest.raises(HTTPException, match='import_invalid_records'):
        workspace_restore._validate_records(rows, module)


@pytest.mark.parametrize('later_work', [False, True])
def test_early_transfer_undo_removes_only_untouched_new_cage(client, monkeypatch, later_work):
    monkeypatch.setattr(module, 'now_of', lambda db: datetime(2026, 9, 12, 11))
    source = create(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/injection-preparation", json={
        'at': '2026-09-02T10:00', 'genotype': 'w1118'})
    bottle = response.json()['bottle']
    response = client.post(f"/api/containers/{source['id']}/injection-actions", json={
        'action': 'injection_collect', 'at': '2026-09-11T10:00', 'female_count': 200, 'male_count': 50})
    assert response.status_code == 200, response.text
    response = client.post(f"/api/containers/{bottle['id']}/injection-actions", json={
        'action': 'injection_transfer', 'at': '2026-09-12T10:00'})
    assert response.status_code == 200, response.text
    cage = response.json()['cage']
    with module.database() as db:
        lid = db.execute("SELECT id FROM logs WHERE container_id=? AND action='injection_transfer'", (bottle['id'],)).fetchone()[0]
        if later_work:
            module.log(db, cage['id'], 'image', '2026-09-12T10:30')
    if later_work:
        shown = preview(client, bottle['id'], lid)
        assert not shown['can_delete'] and shown['keep_later']['can_delete']
    else:
        undo(client, bottle['id'], lid)
        with module.database() as db:
            assert module.get_container(db, bottle['id'])['status'] == 'active'
            assert not db.execute('SELECT 1 FROM containers WHERE id=?', (cage['id'],)).fetchone()
            assert not db.execute('PRAGMA foreign_key_check').fetchall()
            workspace_restore._validate_records(workspace_restore._read_rows(db), module)


@pytest.mark.parametrize('role', ['conditioning', 'cage'])
def test_restore_rejects_ambiguous_injection_destinations(client, role):
    source, bottle, _ = begin(client)
    destination = bottle
    if role == 'cage':
        collect(source, bottle)
        with module.database() as db:
            destination = child(db, bottle, 'cage', injection('cage', 'awaiting_transfer', started_at=bottle['injection']['started_at']))
    with module.database() as db:
        rows = workspace_restore._read_rows(db)
    duplicate = deepcopy(destination)
    duplicate.update(id='duplicate-injection-child', label='Duplicate injection child')
    rows['containers'].append({'id': duplicate['id'], 'label': duplicate['label'], 'payload': json.dumps(duplicate)})
    with pytest.raises(HTTPException, match='import_invalid_records'):
        workspace_restore._validate_records(rows, module)


def test_restore_rejects_collecting_source_without_planned_destination(client):
    source, bottle, _ = begin(client)
    with module.database() as db:
        rows = workspace_restore._read_rows(db)
    rows['containers'] = [row for row in rows['containers'] if row['id'] != bottle['id']]
    for table in ('events', 'logs', 'temperatures', 'plans'):
        rows[table] = [row for row in rows[table] if row['container_id'] != bottle['id']]
    with pytest.raises(HTTPException, match='import_invalid_records'):
        workspace_restore._validate_records(rows, module)
