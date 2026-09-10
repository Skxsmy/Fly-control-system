"""Permanent deletion only exercises temporary databases, never user records."""
import json
import sqlite3

import pytest
from fastapi import HTTPException

from backend import app as module
from backend import container_cleanup as cleanup
from backend.test_app import client, create
from backend.test_eggs import batch, collect, dish, laying


def preview(cid):
    with module.database() as db:
        return cleanup.preview_container_deletion(db, cid)


def delete(cid, backup_dir, before=None, label=None, fingerprint=None):
    before = before or preview(cid)
    with module.database() as db:
        return cleanup.delete_container_permanently(
            db, cid, before["label"] if label is None else label,
            before["fingerprint"] if fingerprint is None else fingerprint, backup_dir)


def database_dump():
    with module.database() as db:
        return list(db.iterdump())


def test_preview_is_read_only_and_counts_all_owned_records(client):
    c = create(client)
    with module.database() as db:
        db.execute("INSERT INTO temperatures VALUES('temperature',?,?,25)", (c['id'], '2026-09-02T09:00'))
        db.execute("INSERT INTO plans VALUES('plan',?,?)", (c['id'], '{}'))
    before = database_dump()
    result = preview(c['id'])
    assert result['id'] == c['id'] and result['label'] == c['label']
    assert result['can_delete'] and result['blockers'] == []
    assert result['counts']['containers'] == result['counts']['temperatures'] == result['counts']['plans'] == 1
    assert result['counts']['logs'] == 1 and result['counts']['events'] > 0
    assert result['counts']['egg_batches'] == 0
    assert result['fingerprint'] == preview(c['id'])['fingerprint']
    assert database_dump() == before


def test_delete_removes_only_selected_container_and_backs_up_all_original_data(client, tmp_path):
    c, other = create(client), create(client, label='Real culture')
    with module.database() as db:
        db.execute("INSERT INTO temperatures VALUES('temperature',?,?,25)", (c['id'], '2026-09-02T09:00'))
        db.execute("INSERT INTO plans VALUES('plan',?,?)", (c['id'], '{}'))
        unaffected = [tuple(r) for r in db.execute('SELECT * FROM events WHERE container_id=?', (other['id'],))]
    before = database_dump()
    result = delete(c['id'], tmp_path / 'backups')
    assert result['deleted'] == c['id']
    backup_file = tmp_path / 'backups' / result['backup']
    with sqlite3.connect(backup_file) as restored:
        assert list(restored.iterdump()) == before
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    with module.database() as db:
        assert db.execute('SELECT id FROM containers').fetchone()[0] == other['id']
        for table in cleanup.OWNED_TABLES:
            assert not db.execute(f'SELECT 1 FROM {table} WHERE container_id=?', (c['id'],)).fetchone()
        assert [tuple(r) for r in db.execute('SELECT * FROM events WHERE container_id=?', (other['id'],))] == unaffected
        assert not db.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize(('label', 'fingerprint', 'detail'), [
    ('wrong', None, 'deletion_label_mismatch'),
    (None, 'outdated-or-missing', 'deletion_preview_changed'),
])
def test_delete_requires_exact_confirmation_without_writing(client, tmp_path, label, fingerprint, detail):
    c = create(client)
    before = database_dump()
    with pytest.raises(HTTPException) as error:
        delete(c['id'], tmp_path / 'backups', label=label, fingerprint=fingerprint)
    assert error.value.detail == detail
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()


def test_preview_becomes_stale_after_history_changes(client, tmp_path):
    c = create(client)
    shown = preview(c['id'])
    with module.database() as db:
        module.log(db, c['id'], 'check', '2026-09-09T10:00', 'New observation after opening dialog')
    with pytest.raises(HTTPException, match='deletion_preview_changed'):
        delete(c['id'], tmp_path / 'backups', before=shown)
    assert preview(c['id'])['counts']['logs'] == 2


def test_unrelated_record_changes_do_not_stale_preview(client, tmp_path):
    c = create(client)
    shown = preview(c['id'])
    other = create(client, label='Unrelated culture')
    assert preview(c['id'])['fingerprint'] == shown['fingerprint']
    delete(c['id'], tmp_path / 'backups', before=shown)
    assert preview(other['id'])['can_delete']


def test_descendant_blocks_source_deletion_even_after_archiving(client, tmp_path):
    source = create(client)
    child = create(client)
    with module.database() as db:
        child.update(source_id=source['id'], status='completed')
        module.save_container(db, child)
    result = preview(source['id'])
    assert not result['can_delete']
    assert result['blockers'] == [{'type': 'container', 'id': child['id'], 'label': child['label'], 'reasons': ['source_container']}]
    before = database_dump()
    with pytest.raises(HTTPException, match='container_has_dependents'):
        delete(source['id'], tmp_path / 'backups')
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()


def test_new_descendant_is_checked_again_at_delete_time(client, tmp_path):
    source = create(client)
    shown = preview(source['id'])
    child = create(client)
    with module.database() as db:
        child['source_id'] = source['id']
        module.save_container(db, child)
    with pytest.raises(HTTPException, match='container_has_dependents'):
        delete(source['id'], tmp_path / 'backups', before=shown)


def test_batch_link_alone_blocks_deletion_and_deleting_dish_preserves_batch(client, tmp_path):
    source = laying(client)
    eggs = batch(client, source)
    collect(client, eggs)
    child = dish(client, eggs)
    with module.database() as db:
        child['source_id'] = None
        module.save_container(db, child)
    assert preview(source['id'])['blockers'][0]['reasons'] == ['egg_batch']
    with pytest.raises(HTTPException, match='container_has_dependents'):
        delete(source['id'], tmp_path / 'backups')
    delete(child['id'], tmp_path / 'backups')
    with module.database() as db:
        assert module.get_egg_batch(db, eggs['id'])['source_id'] == source['id']
        assert module.get_container(db, source['id']) == source
    assert preview(source['id'])['can_delete']


def test_unreferenced_batches_and_their_history_are_in_preview_and_backup(client, tmp_path):
    source = laying(client)
    eggs = batch(client, source)
    collect(client, eggs)
    assert preview(source['id'])['counts']['egg_batches'] == 1
    result = delete(source['id'], tmp_path / 'backups')
    with module.database() as db:
        assert not db.execute('SELECT * FROM egg_batches').fetchall()
        assert not db.execute('SELECT * FROM events').fetchall()
    with sqlite3.connect(tmp_path / 'backups' / result['backup']) as restored:
        stored = json.loads(restored.execute('SELECT payload FROM egg_batches').fetchone()[0])
        assert stored['id'] == eggs['id'] and stored['status'] == 'collected'


def test_external_batch_reminder_prevents_orphaning(client, tmp_path):
    source = laying(client)
    eggs = batch(client, source)
    with module.database() as db:
        module.save_event(db, {'id': 'external', 'rule_key': 'custom-external', 'container_id': None,
                              'egg_batch_id': eggs['id'], 'title': 'Imaging appointment'})
    assert preview(source['id'])['blockers'] == [
        {'type': 'event', 'id': 'external', 'label': 'Imaging appointment', 'reasons': ['egg_batch']}]
    with pytest.raises(HTTPException, match='container_has_dependents'):
        delete(source['id'], tmp_path / 'backups')


def test_backup_failure_leaves_all_data_untouched(client, tmp_path, monkeypatch):
    c = create(client)
    before = database_dump()
    def fail_backup(*_):
        raise HTTPException(500, 'deletion_backup_failed')
    monkeypatch.setattr(cleanup, '_backup_before_delete', fail_backup)
    with pytest.raises(HTTPException, match='deletion_backup_failed'):
        delete(c['id'], tmp_path / 'backups')
    assert database_dump() == before


def test_unwritable_backup_destination_prevents_deletion(client, tmp_path):
    c = create(client)
    before = database_dump()
    destination = tmp_path / 'not-a-directory'
    destination.write_text('Keep existing file', encoding='utf-8')
    with pytest.raises(HTTPException, match='deletion_backup_failed'):
        delete(c['id'], destination)
    assert database_dump() == before
    assert destination.read_text(encoding='utf-8') == 'Keep existing file'


def test_delete_rolls_back_all_owned_rows_if_a_later_delete_fails(client, tmp_path):
    c = create(client)
    with module.database() as db:
        db.execute("INSERT INTO temperatures VALUES('temperature',?,?,25)", (c['id'], '2026-09-02T09:00'))
        db.execute("CREATE TRIGGER prevent_log_delete BEFORE DELETE ON logs BEGIN SELECT RAISE(ABORT, 'test failure'); END")
    shown = preview(c['id'])
    before = database_dump()
    with module.database() as db:
        # Even a caller that catches the error and commits must not persist a
        # partially deleted history: the helper owns an explicit savepoint.
        with pytest.raises(sqlite3.IntegrityError, match='test failure'):
            cleanup.delete_container_permanently(db, c['id'], shown['label'], shown['fingerprint'], tmp_path / 'backups')
    assert database_dump() == before
    assert len(list((tmp_path / 'backups').glob('*.db'))) == 1


def test_label_allocator_uses_gaps_per_kind_and_respects_all_existing_labels(client):
    first = create(client, label='V0001')
    create(client, label='V0003')
    create(client, kind='bottle', label='B0001')
    create(client, kind='bottle', label='V0002')
    with module.database() as db:
        first['status'] = 'discarded'
        module.save_container(db, first)
        assert cleanup.next_container_label(db, 'vial') == 'V0004'
        assert cleanup.next_container_label(db, 'bottle') == 'B0002'
        assert cleanup.next_container_label(db, 'egg_laying') == 'E0001'
        assert cleanup.next_container_label(db, 'petri_dish') == 'P0001'


def test_deleted_label_can_be_reused_without_reusing_internal_id(client, tmp_path):
    old = create(client, label='V0001')
    preserved = create(client, label='V0002')
    delete(old['id'], tmp_path / 'backups')
    with module.database() as db:
        label = cleanup.next_container_label(db, 'vial')
    assert label == 'V0001'
    new = create(client, label=label)
    assert new['id'] != old['id']
    with module.database() as db:
        assert module.get_container(db, preserved['id']) == preserved
        assert not db.execute('SELECT 1 FROM containers WHERE id=?', (old['id'],)).fetchone()


def test_missing_container_is_404(client):
    with pytest.raises(HTTPException) as error:
        preview('missing')
    assert error.value.status_code == 404


def test_api_delete_preview_confirmation_and_automatic_label_reuse(client, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    old = create(client)
    other = create(client, kind='bottle')
    assert old['label'] == 'V0001' and other['label'] == 'B0001'
    before = database_dump()
    response = client.get(f"/api/containers/{old['id']}/delete-preview")
    assert response.status_code == 200
    shown = response.json()
    assert shown['can_delete'] and shown['counts']['events'] > 0
    assert database_dump() == before

    response = client.request('DELETE', f"/api/containers/{old['id']}", json={
        'confirmation_label': 'V0001 ', 'fingerprint': shown['fingerprint']})
    assert response.status_code == 422 and response.json()['detail'] == 'deletion_label_mismatch'
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()

    response = client.request('DELETE', f"/api/containers/{old['id']}", json={
        'confirmation_label': shown['label'], 'fingerprint': shown['fingerprint']})
    assert response.status_code == 200, response.text
    assert (tmp_path / 'backups' / response.json()['backup']).is_file()
    state = client.get('/api/state').json()
    assert {c['id'] for c in state['containers']} == {other['id']}
    assert all(e['container_id'] != old['id'] for e in state['events'])
    assert client.get(f"/api/containers/{old['id']}/delete-preview").status_code == 404

    new = create(client)
    assert new['label'] == old['label'] == 'V0001'
    assert new['id'] != old['id']
    with module.database() as db:
        assert module.get_container(db, other['id']) == other


def test_api_deletion_does_not_cascade_through_transfer_lineage(client, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    source = create(client, purpose='stock', genotype='w1118')
    response = client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'generation', 'purpose': 'stock', 'genotype': 'w1118',
        'setup_date': '2026-09-03', 'setup_time': '10:00'})
    assert response.status_code == 200, response.text
    child = response.json()
    assert child['source_id'] == source['id']
    shown = client.get(f"/api/containers/{source['id']}/delete-preview").json()
    assert not shown['can_delete'] and shown['blockers'][0]['id'] == child['id']
    before = database_dump()
    response = client.request('DELETE', f"/api/containers/{source['id']}", json={
        'confirmation_label': shown['label'], 'fingerprint': shown['fingerprint']})
    assert response.status_code == 409 and response.json()['detail'] == 'container_has_dependents'
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()


def test_api_requires_refreshing_stale_delete_preview(client, tmp_path, monkeypatch):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    c = create(client)
    shown = client.get(f"/api/containers/{c['id']}/delete-preview").json()
    response = client.post(f"/api/containers/{c['id']}/actions", json={
        'action': 'larvae', 'at': '2026-09-09T10:00', 'notes': 'New result entered after preview'})
    assert response.status_code == 200, response.text
    before = database_dump()
    response = client.request('DELETE', f"/api/containers/{c['id']}", json={
        'confirmation_label': shown['label'], 'fingerprint': shown['fingerprint']})
    assert response.status_code == 409 and response.json()['detail'] == 'deletion_preview_changed'
    assert database_dump() == before
    assert not (tmp_path / 'backups').exists()


def test_single_day_migration_preserves_all_records_and_is_idempotent(client):
    c = create(client)
    source = laying(client)
    eggs = batch(client, source)
    collect(client, eggs)
    dish(client, eggs)
    with module.database() as db:
        db.execute("DELETE FROM meta WHERE key='single_day_collection_v1'")
        settings = module.settings_of(db)
        settings['template']['collection_days'] = 3
        db.execute("UPDATE meta SET value=? WHERE key='settings'", (module.dump(settings),))
        expected_containers = {}
        for row in db.execute('SELECT id,payload FROM containers').fetchall():
            value = json.loads(row['payload'])
            value['template']['collection_days'] = 3
            module.save_container(db, value)
            value['template']['collection_days'] = 1
            expected_containers[value['id']] = value
        # Include a preexisting extra-day pinned reminder with recorded status.
        module.save_event(db, {'id': 'legacy-day-two', 'container_id': c['id'],
            'rule_key': 'collect-1-09:00-11:00', 'kind': 'collect', 'status': 'done',
            'pinned': True, 'due': '2026-09-12T09:00', 'end': '2026-09-12T11:00'})
        untouched_tables = {table: [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')]
                            for table in (*cleanup.OWNED_TABLES, 'egg_batches')}

    module.init_db()
    with module.database() as db:
        assert module.settings_of(db)['template']['collection_days'] == 1
        assert {row['id']: json.loads(row['payload']) for row in db.execute('SELECT * FROM containers')} == expected_containers
        for table, before in untouched_tables.items():
            assert [tuple(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY id')] == before
        assert not db.execute('PRAGMA foreign_key_check').fetchall()
    migrated = database_dump()
    module.init_db()
    assert database_dump() == migrated
