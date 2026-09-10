"""Workspace restore tests use temporary databases and staged uploads only."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import app as module
from backend import workspace_restore as restore
from backend.test_app import client, create, snapshot
from backend.test_eggs import batch, collect, dish, laying


@pytest.fixture
def importer(client, tmp_path):
    instance = restore.WorkspaceImporter(module, backup_dir=tmp_path / 'recovery')
    yield instance
    instance.close()


def records():
    with module.database() as db:
        return restore._read_rows(db)


def uploaded_backup(tmp_path):
    path = tmp_path / 'uploaded.db'
    with closing(sqlite3.connect(module.DB_PATH)) as source:
        with closing(sqlite3.connect(path)) as target:
            source.backup(target)
    return path


def restore_input(preview, **changes):
    return restore.RestoreInput(token=preview['token'], confirmation='RESTORE',
                                expected_current_fingerprint=preview['current_fingerprint']).model_copy(update=changes)


def populate(client):
    source = create(client, kind='bottle', purpose='larvae', genotype='w1118', label='Larval culture')
    eggs_source = laying(client)
    eggs = batch(client, eggs_source)
    collect(client, eggs)
    plated = dish(client, eggs)
    client.post(f"/api/egg-batches/{eggs['id']}/actions", json={
        'action': 'use', 'purpose': 'imaging', 'at': '2026-09-09T10:00', 'notes': 'Slide aliquot'})
    response = client.post(f"/api/containers/{source['id']}/actions", json={
        'action': 'cold', 'at': '2026-09-03T10:00', 'notes': 'Incubator'})
    assert response.status_code == 200
    client.put('/api/availability', json={'date': '2026-09-15', 'kind': 'leave', 'notes': 'Away'})
    event = next(e for e in snapshot(client)['events'] if e['container_id'] == source['id'] and e['kind'] == 'third_instar')
    client.patch(f"/api/events/{event['id']}", json={'due': '2026-09-06T11:00', 'end': '2026-09-06T12:00'})
    with module.database() as db:
        plan = {'id': 'cooling-plan', 'container_id': source['id'], 'cold_at': '2026-09-03T10:00',
                'warm_at': '2026-09-04T10:00', 'hours': 24, 'collection_date': '2026-09-12', 'events': []}
        db.execute('INSERT INTO plans VALUES(?,?,?)', (plan['id'], source['id'], module.dump(plan)))
    return source, eggs_source, eggs, plated


def test_preview_roundtrip_preserves_exact_records_and_full_recovery_backup(client, importer, tmp_path):
    populate(client)
    original = records()
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client, label='Created after backup')
    before_restore = records()
    preview = importer.preview(incoming)
    assert preview['incoming']['counts']['containers'] == 3
    assert preview['incoming']['counts']['egg_batches'] == 1
    assert preview['current']['counts']['containers'] == 4
    assert preview['incoming']['timezone'] == 'Asia/Shanghai'
    assert records() == before_restore
    result = importer.restore(restore_input(preview))
    assert result['restored'] is True and result['counts']['containers'] == 3
    assert records() == original
    staged = importer._staged[preview['token']]
    assert not staged.path.exists()
    recovery = tmp_path / 'recovery' / result['backup']
    assert restore.validate_snapshot(recovery, module) == before_restore
    # The recovery snapshot is itself importable and restores the replaced work.
    recovery_preview = importer.preview(recovery.read_bytes())
    importer.restore(restore_input(recovery_preview))
    assert records() == before_restore


def test_restore_retry_is_idempotent_even_after_new_work(client, importer, tmp_path):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client, label='Newer')
    preview = importer.preview(incoming)
    request = restore_input(preview)
    first = importer.restore(request)
    create(client, label='After restoration')
    current = records()
    assert importer.restore(request) == first
    assert records() == current
    assert len(list((tmp_path / 'recovery').glob('*.db'))) == 1
    with pytest.raises(HTTPException, match='import_workspace_changed'):
        importer.restore(restore_input(preview, expected_current_fingerprint='different'))


@pytest.mark.parametrize('payload', [b'', b'not a database', b'SQLite format 3\x00broken'])
def test_invalid_sqlite_does_not_change_workspace_or_leave_uploads(client, importer, payload):
    create(client)
    before = records()
    with pytest.raises(HTTPException, match='import_invalid_file'):
        importer.preview(payload)
    assert records() == before
    assert not list(importer._staged)
    assert not list(Path(importer._directory.name).iterdir())


@pytest.mark.parametrize('change,detail', [
    ("DROP TABLE logs", 'import_unsupported_schema'),
    ("CREATE TABLE unexpected(id TEXT)", 'import_unsupported_schema'),
    ("CREATE VIEW stolen AS SELECT * FROM containers", 'import_unsupported_schema'),
    ("CREATE TRIGGER imported_trigger AFTER INSERT ON logs BEGIN DELETE FROM events; END", 'import_unsupported_schema'),
    ("UPDATE meta SET value='2' WHERE key='schema_version'", 'import_unsupported_schema'),
    ("UPDATE containers SET payload='not JSON'", 'import_invalid_records'),
    ("UPDATE containers SET payload='[]'", 'import_invalid_records'),
    ("UPDATE containers SET payload=json_set(payload,'$.id','different')", 'import_invalid_records'),
    ("UPDATE containers SET payload=json_set(payload,'$.source_id','missing')", 'import_invalid_records'),
    ("UPDATE containers SET payload=json_set(payload,'$.transfer_index','3')", 'import_invalid_records'),
    ("UPDATE containers SET payload=json_set(payload,'$.template.rate18',0)", 'import_invalid_records'),
    ("UPDATE containers SET payload=json_set(payload,'$.template.collection_days',3)", 'import_invalid_records'),
    ("UPDATE events SET payload=json_set(payload,'$.container_id','missing')", 'import_invalid_records'),
    ("UPDATE events SET payload=json_set(payload,'$.due','bad date')", 'import_invalid_records'),
    ("UPDATE events SET payload=json_set(payload,'$.end','2020-01-01T09:00')", 'import_invalid_records'),
    ("UPDATE events SET container_id='missing'", 'import_invalid_records'),
    ("UPDATE meta SET value=json_set(value,'$.timezone','Not/AZone') WHERE key='settings'", 'import_invalid_records'),
    ("UPDATE meta SET value=json_set(value,'$.weekly.0[0][1]','08:00') WHERE key='settings'", 'import_invalid_records'),
])
def test_rejects_unsupported_schema_and_inconsistent_records(client, importer, tmp_path, change, detail):
    create(client)
    before = records()
    path = uploaded_backup(tmp_path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(change)
    with pytest.raises(HTTPException, match=detail):
        importer.preview(path.read_bytes())
    assert records() == before
    assert not importer._staged


def test_source_cycle_is_rejected(client, importer, tmp_path):
    left, right = create(client), create(client)
    path = uploaded_backup(tmp_path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE containers SET payload=json_set(payload,'$.source_id',?) WHERE id=?", (left['id'], right['id']))
        db.execute("UPDATE containers SET payload=json_set(payload,'$.source_id',?) WHERE id=?", (right['id'], left['id']))
    with pytest.raises(HTTPException, match='import_invalid_records'):
        importer.preview(path.read_bytes())


@pytest.mark.parametrize('change', [
    "UPDATE egg_batches SET payload=json_set(payload,'$.source_id','missing')",
    "UPDATE egg_batches SET payload=json_set(payload,'$.id','mismatch')",
    "UPDATE egg_batches SET payload=json_set(payload,'$.collected_at',NULL)",
    "UPDATE containers SET payload=json_set(payload,'$.egg_batch_id','missing') WHERE json_extract(payload,'$.kind')='petri_dish'",
    "UPDATE containers SET payload=json_set(payload,'$.incubation.lay_start','2026-09-08T08:00') WHERE json_extract(payload,'$.kind')='petri_dish'",
])
def test_egg_batch_payload_and_dish_links_are_validated(client, importer, tmp_path, change):
    populate(client)
    before = records()
    path = uploaded_backup(tmp_path)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(change)
    with pytest.raises(HTTPException, match='import_invalid_records'):
        importer.preview(path.read_bytes())
    assert records() == before


def test_workspace_changes_stale_preview_but_clock_passage_does_not(client, importer, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    preview = importer.preview(incoming)
    monkeypatch.setattr(module, 'now_of', lambda _: datetime(2027, 3, 1, 11, 30))
    snapshot(client)
    with module.database() as db:
        assert restore.workspace_fingerprint(db) == preview['current_fingerprint']
    create(client, label='More work')
    before = records()
    with pytest.raises(HTTPException, match='import_workspace_changed'):
        importer.restore(restore_input(preview))
    assert records() == before
    assert not (tmp_path / 'recovery').exists()


def test_wrong_confirmation_and_expiry_leave_workspace_unchanged(client, importer, tmp_path):
    create(client)
    before = records()
    preview = importer.preview(uploaded_backup(tmp_path).read_bytes())
    with pytest.raises(HTTPException, match='import_confirmation_required'):
        importer.restore(restore_input(preview, confirmation='restore'))
    staged = importer._staged[preview['token']]
    staged.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with pytest.raises(HTTPException, match='import_upload_expired'):
        importer.restore(restore_input(preview))
    assert records() == before
    assert not staged.path.exists()


def test_tampered_staged_file_is_revalidated(client, importer, tmp_path):
    c = create(client)
    preview = importer.preview(uploaded_backup(tmp_path).read_bytes())
    before = records()
    path = importer._staged[preview['token']].path
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE containers SET payload=json_set(payload,'$.notes','changed') WHERE id=?", (c['id'],))
    with pytest.raises(HTTPException, match='import_invalid_file'):
        importer.restore(restore_input(preview))
    assert records() == before
    assert not path.exists()


def test_backup_failure_prevents_restore(client, importer, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client)
    preview = importer.preview(incoming)
    before = records()
    def fail(*_):
        raise HTTPException(500, 'import_backup_failed')
    monkeypatch.setattr(restore, 'backup_current_workspace', fail)
    with pytest.raises(HTTPException, match='import_backup_failed'):
        importer.restore(restore_input(preview))
    assert records() == before


def test_unwritable_recovery_destination_prevents_restore(client, importer, tmp_path):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client)
    preview = importer.preview(incoming)
    before = records()
    blocked = tmp_path / 'existing-file'
    blocked.write_text('Keep me', encoding='utf-8')
    importer.backup_dir = blocked
    with pytest.raises(HTTPException, match='import_backup_failed'):
        importer.restore(restore_input(preview))
    assert records() == before
    assert blocked.read_text(encoding='utf-8') == 'Keep me'


def test_mid_restore_failure_rolls_back_every_table(client, importer, tmp_path):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client, label='Keep this if restore fails')
    with module.database() as db:
        db.execute("CREATE TRIGGER prevent_delete BEFORE DELETE ON containers BEGIN SELECT RAISE(ABORT,'test failure'); END")
    preview = importer.preview(incoming)
    before = records()
    with pytest.raises(HTTPException, match='import_restore_failed'):
        importer.restore(restore_input(preview))
    assert records() == before
    assert len(list((tmp_path / 'recovery').glob('*.db'))) == 1


def test_connection_config_stays_local(client, importer, tmp_path):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    connection_file = module.DB_PATH.with_name('.' + module.DB_PATH.name + '.ai-settings.json')
    connection_file.write_text('{"provider":"local"}', encoding='utf-8')
    preview = importer.preview(incoming)
    importer.restore(restore_input(preview))
    assert connection_file.read_text(encoding='utf-8') == '{"provider":"local"}'


def test_http_upload_and_confirmation_contract(client, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    api = FastAPI()
    api.include_router(restore.make_router(module))
    with TestClient(api) as http:
        assert http.post('/api/import/preview', content=incoming, headers={'content-type': 'text/plain'}).status_code == 415
        preview = http.post('/api/import/preview', content=incoming, headers={'content-type': 'application/octet-stream'})
        assert preview.status_code == 200, preview.text
        response = http.post('/api/import/restore', json=restore_input(preview.json()).model_dump())
        assert response.status_code == 200, response.text
        assert response.json()['restored'] is True
        monkeypatch.setattr(restore, 'MAX_UPLOAD_BYTES', 16)
        assert http.post('/api/import/preview', content=incoming, headers={'content-type': 'application/octet-stream'}).status_code == 413


def test_streamed_upload_size_is_bounded_without_content_length(client, tmp_path, monkeypatch):
    api = FastAPI()
    api.include_router(restore.make_router(module))
    monkeypatch.setattr(restore, 'MAX_UPLOAD_BYTES', 16)
    with TestClient(api) as http:
        result = http.post('/api/import/preview', content=iter([b'a' * 10, b'b' * 10]),
                           headers={'content-type': 'application/octet-stream'})
        assert result.status_code == 413


def test_real_app_mount_and_repeated_lifespans_use_import_routes(client, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    for _ in range(2):
        with TestClient(module.app) as http:
            assert http.get('/api/ai/settings').status_code == 200
            preview = http.post('/api/import/preview', content=incoming,
                                headers={'content-type': 'application/octet-stream'})
            assert preview.status_code == 200, preview.text
            result = http.post('/api/import/restore', json=restore_input(preview.json()).model_dump())
            assert result.status_code == 200 and result.json()['restored']


def test_recovery_download_returns_exact_automatic_backup(client, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    create(client, label='Recovery preserves this')
    before = records()
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    with TestClient(module.app) as http:
        preview = http.post('/api/import/preview', content=incoming,
                            headers={'content-type': 'application/octet-stream'}).json()
        result = http.post('/api/import/restore', json=restore_input(preview).model_dump()).json()
        download = http.get('/api/import/recovery/' + result['backup'])
        assert download.status_code == 200
        assert download.headers['content-type'] == 'application/vnd.sqlite3'
        assert result['backup'] in download.headers['content-disposition']
        path = tmp_path / 'downloaded.db'
        path.write_bytes(download.content)
        assert restore.validate_snapshot(path, module) == before
        assert download.content == (tmp_path / 'backups' / result['backup']).read_bytes()


@pytest.mark.parametrize('filename', [
    'test.db', 'settings.json', '..%5Ctest.db', '..%2Ftest.db',
    'flykeeper-before-restore-20260910T120000000000Z-0123abcd.db',
])
def test_recovery_download_rejects_arbitrary_traversal_and_missing_files(client, tmp_path, monkeypatch, filename):
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    (tmp_path / 'backups').mkdir()
    (tmp_path / 'backups' / 'test.db').write_bytes(b'SQLite format 3\x00private file')
    with TestClient(module.app) as http:
        response = http.get('/api/import/recovery/' + filename)
        assert response.status_code == 404
        assert b'private file' not in response.content


def test_recovery_download_rejects_non_sqlite_disguised_as_recovery(client, importer, tmp_path):
    folder = tmp_path / 'recovery'
    folder.mkdir()
    filename = 'flykeeper-before-restore-20260910T120000000000Z-0123abcd.db'
    (folder / filename).write_text('Unrelated private file', encoding='utf-8')
    with pytest.raises(HTTPException, match='import_recovery_not_found'):
        importer.recovery_file(filename)


def test_recovery_download_rejects_symlink_outside_backup_directory(client, importer, tmp_path):
    folder = tmp_path / 'recovery'
    folder.mkdir()
    outside = tmp_path / 'outside.db'
    outside.write_bytes(b'SQLite format 3\x00private file')
    filename = 'flykeeper-before-restore-20260910T120000000000Z-0123abcd.db'
    try:
        (folder / filename).symlink_to(outside)
    except OSError:
        pytest.skip('Creating symlinks requires Windows developer mode or appropriate permissions')
    with pytest.raises(HTTPException, match='import_recovery_not_found'):
        importer.recovery_file(filename)


def test_record_limit_has_distinct_error(client, importer, tmp_path, monkeypatch):
    create(client)
    incoming = uploaded_backup(tmp_path).read_bytes()
    monkeypatch.setattr(restore, 'MAX_IMPORTED_RECORDS', 1)
    with pytest.raises(HTTPException, match='import_too_many_records'):
        importer.preview(incoming)
