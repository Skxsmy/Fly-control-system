"""Explicit record-only correction retains subsequent and physical work."""
import json
import sqlite3

import pytest
from fastapi import HTTPException

from backend import activity_cleanup, activity_record_cleanup, app as module
from backend.test_app import client, create
from backend.test_activity_cleanup import (
    container, delete, events, isolated_backup_root, make_legacy, preview, record,
)
from backend.test_workspace_restore import importer, restore_input


def physical_rows():
    with module.database() as db:
        return activity_cleanup.snapshot(db)


def metadata():
    with module.database() as db:
        return {row['key']: row['value'] for row in db.execute('SELECT key,value FROM meta')}


def keep_later(client, cid, lid, shown=None, **extra):
    shown = shown if shown is not None else preview(client, cid, lid)
    return client.request('DELETE', f'/api/containers/{cid}/activities/{lid}', json={
        'mode': 'keep_later', 'fingerprint': shown['keep_later']['fingerprint'], **extra,
    })


def assert_only_selected_log_removed(before, lid):
    expected = {table: dict(rows) for table, rows in before.items()}
    expected['logs'].pop(lid)
    assert physical_rows() == expected


def test_delete_earlier_stage_retains_later_state_and_later_journal(client):
    culture = create(client)
    earlier = record(client, culture, 'larvae', at='2026-09-06T09:00')
    later = record(client, culture, 'pupae', at='2026-09-07T09:00')
    shown = preview(client, culture['id'], earlier['id'])
    assert not shown['can_delete'] and shown['keep_later']['can_delete']
    before, journals = physical_rows(), metadata()
    response = keep_later(client, culture['id'], earlier['id'], shown)
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, earlier['id'])
    assert activity_cleanup.PREFIX + earlier['id'] not in metadata()
    later_key = activity_cleanup.PREFIX + later['id']
    assert metadata()[later_key] == journals[later_key]
    assert delete(client, culture['id'], later['id']).status_code == 200
    restored = container(client, culture['id'])
    assert restored['stage'] == 'larvae'  # The retained physical observation.
    assert earlier['id'] not in {row['id'] for row in restored['logs']}


def test_delete_temperature_record_keeps_segments_and_forecasts(client):
    culture = create(client)
    earlier = record(client, culture, 'cold', at='2026-09-03T09:00')
    later = record(client, culture, 'warm', at='2026-09-05T09:00')
    before = physical_rows()
    response = keep_later(client, culture['id'], earlier['id'])
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, earlier['id'])
    assert delete(client, culture['id'], later['id']).status_code == 200
    assert container(client, culture['id'])['temperature'] == 18


def test_delete_transfer_record_keeps_child_parent_state_and_reminders(client):
    source = create(client, kind='bottle')
    response = client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'transfer', 'kind': 'vial', 'purpose': 'cross',
        'female_genotype': source['female_genotype'], 'male_genotype': source['male_genotype'],
        'setup_date': '2026-09-03', 'setup_time': '11:00',
    })
    assert response.status_code == 200, response.text
    child = response.json()
    activity = next(row for row in container(client, source['id'])['logs'] if row['action'] == 'transfer')
    shown = preview(client, source['id'], activity['id'])
    assert not shown['can_delete'] and shown['keep_later']['can_delete']
    before = physical_rows()
    response = keep_later(client, source['id'], activity['id'], shown)
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, activity['id'])
    assert container(client, child['id'])['transfer_index'] == 1
    assert container(client, source['id'])['parents'] == 'transferred'


@pytest.mark.parametrize('selected_action', ['clear', 'collect'])
def test_grouped_record_deletion_keeps_companion_and_reports_clock_effect(client, selected_action):
    culture = create(client)
    task = next(row for row in events(client, culture['id']).values() if row['kind'] == 'collect')
    collection = record(client, culture, 'collect', event_id=task['id'], cleared=True)
    clear = next(row for row in container(client, culture['id'])['logs'] if row['action'] == 'clear')
    selected = clear if selected_action == 'clear' else collection
    shown = preview(client, culture['id'], selected['id'])
    effects = shown['keep_later']['effects']
    assert 'forget_group_undo' in effects
    assert ('recalculate_virgin_clock' in effects) == (selected_action == 'clear')
    before = physical_rows()
    response = keep_later(client, culture['id'], selected['id'], shown)
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, selected['id'])
    after = container(client, culture['id'])
    assert after['parents'] == 'removed'
    assert events(client, culture['id'])[task['id']]['status'] == 'done'
    assert after['clock']['last_clear'] == (None if selected_action == 'clear' else clear['at'])
    assert activity_cleanup.PREFIX + collection['id'] not in metadata()


def test_legacy_record_deletion_keeps_other_operations_and_reminder_status(client):
    culture = create(client, purpose='larvae', genotype='w1118')
    earlier = record(client, culture, 'third_instar')
    make_legacy(earlier['id'])
    record(client, culture, 'remove')
    before, old_meta = physical_rows(), metadata()
    response = keep_later(client, culture['id'], earlier['id'])
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, earlier['id'])
    assert all(metadata().get(key) == value for key, value in old_meta.items())


@pytest.mark.parametrize('invalid_kind', ['invalid_json', 'deep_json', 'wrong_owner', 'oversized', 'invalid_changes'])
def test_invalid_owning_journal_cannot_execute_changes_or_remove_unrelated_metadata(client, invalid_kind):
    culture, other = create(client), create(client)
    selected = record(client, culture, 'tissue')
    unrelated = record(client, other, 'larvae')
    key = activity_cleanup.PREFIX + selected['id']
    with module.database() as db:
        if invalid_kind in ('invalid_json', 'deep_json'):
            raw = '{not valid' if invalid_kind == 'invalid_json' else '[' * 2000 + '0' + ']' * 2000
        else:
            journal = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
            if invalid_kind == 'wrong_owner':
                journal['container_id'] = other['id']
            elif invalid_kind == 'oversized':
                journal = {'version': 1, 'container_id': culture['id'], 'log_ids': [selected['id']],
                           'unavailable': 'journal_too_large'}
            else:
                journal['changes'] = [{'table': 'containers', 'id': other['id'], 'before': None, 'after': None}]
            raw = json.dumps(journal)
        db.execute('UPDATE meta SET value=? WHERE key=?', (raw, key))
    before, old_meta = physical_rows(), metadata()
    shown = preview(client, culture['id'], selected['id'])
    assert not shown['can_delete'] and shown['keep_later']['can_delete']
    response = keep_later(client, culture['id'], selected['id'], shown)
    assert response.status_code == 200, response.text
    assert_only_selected_log_removed(before, selected['id'])
    assert key not in metadata()
    unrelated_key = activity_cleanup.PREFIX + unrelated['id']
    assert metadata()[unrelated_key] == old_meta[unrelated_key]


@pytest.mark.parametrize('change', ['record', 'journal'])
def test_stale_record_or_journal_preview_rejected_before_backup(client, change):
    culture = create(client)
    selected = record(client, culture, 'larvae')
    shown = preview(client, culture['id'], selected['id'])
    with module.database() as db:
        if change == 'record':
            db.execute('UPDATE logs SET notes=? WHERE id=?', ('Later edit', selected['id']))
        else:
            db.execute('UPDATE meta SET value=? WHERE key=?', ('{}', activity_cleanup.PREFIX + selected['id']))
    before, old_meta = physical_rows(), metadata()
    response = keep_later(client, culture['id'], selected['id'], shown)
    assert response.status_code == 409 and response.json()['detail'] == 'activity_preview_changed'
    assert physical_rows() == before and metadata() == old_meta
    assert not list((module.ROOT / 'backups').glob('*.db'))


def test_backup_contains_exact_selected_record_and_journal(client):
    culture = create(client)
    selected = record(client, culture, 'remove')
    before, old_meta = physical_rows(), metadata()
    response = keep_later(client, culture['id'], selected['id'])
    assert response.status_code == 200, response.text
    with sqlite3.connect(module.ROOT / 'backups' / response.json()['backup']) as saved:
        saved.row_factory = sqlite3.Row
        assert activity_cleanup.snapshot(saved) == before
        assert {row['key']: row['value'] for row in saved.execute('SELECT key,value FROM meta')} == old_meta
    from backend.workspace_restore import validate_snapshot
    assert validate_snapshot(module.DB_PATH, module)['logs']


def test_export_and_restore_preserve_deletion_marker_and_later_undo(client, importer):
    culture = create(client)
    selected = record(client, culture, 'larvae', at='2026-09-06T09:00')
    later = record(client, culture, 'pupae', at='2026-09-07T09:00')
    assert keep_later(client, culture['id'], selected['id']).status_code == 200
    expected_rows, expected_meta = physical_rows(), metadata()
    response = client.get('/api/backup')
    assert response.status_code == 200, response.text
    create(client, label='Created after export')
    shown = importer.preview(response.content)
    result = importer.restore(restore_input(shown))
    assert result['restored']
    assert physical_rows() == expected_rows and metadata() == expected_meta
    assert activity_record_cleanup.DELETED_PREFIX + selected['id'] in metadata()
    assert delete(client, culture['id'], later['id']).status_code == 200
    assert selected['id'] not in physical_rows()['logs']


def test_backup_failure_does_not_delete_record_or_metadata(client, monkeypatch):
    culture = create(client)
    selected = record(client, culture, 'larvae')
    before, old_meta = physical_rows(), metadata()

    def fail(*_):
        raise HTTPException(500, 'deletion_backup_failed')

    monkeypatch.setattr(activity_record_cleanup, '_backup_before_delete', fail)
    response = keep_later(client, culture['id'], selected['id'])
    assert response.status_code == 500
    assert physical_rows() == before and metadata() == old_meta


def test_record_deletion_rejects_creation_wrong_owner_and_undo_fields(client):
    culture, other = create(client), create(client)
    created = next(row for row in container(client, culture['id'])['logs'] if row['action'] == 'created')
    shown = preview(client, culture['id'], created['id'])
    assert not shown['keep_later']['can_delete']
    assert keep_later(client, culture['id'], created['id'], shown).status_code == 409
    selected = record(client, culture, 'larvae')
    shown = preview(client, culture['id'], selected['id'])
    before, old_meta = physical_rows(), metadata()
    assert keep_later(client, other['id'], selected['id'], shown).status_code == 404
    assert keep_later(client, culture['id'], selected['id'], shown, corrections={'stage': 'pupae'}).status_code == 422
    assert keep_later(client, culture['id'], selected['id'], shown, reopen_event_ids=['x']).status_code == 422
    assert keep_later(client, culture['id'], selected['id'], shown, mode='unknown').status_code == 422
    assert physical_rows() == before and metadata() == old_meta


def test_unrelated_journal_cannot_resurrect_deleted_record(client):
    culture = create(client)
    selected = record(client, culture, 'tissue')
    later = record(client, culture, 'larvae')
    # Simulate a future/imported operation that removed an older log. Its
    # otherwise valid inverse would restore that row after record deletion.
    key = activity_cleanup.PREFIX + later['id']
    with module.database() as db:
        journal = json.loads(db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0])
        original = dict(db.execute('SELECT * FROM logs WHERE id=?', (selected['id'],)).fetchone())
        journal['changes'].append({'table': 'logs', 'id': selected['id'], 'before': original, 'after': None})
        raw = json.dumps(journal)
        db.execute('UPDATE meta SET value=? WHERE key=?', (raw, key))
    assert keep_later(client, culture['id'], selected['id']).status_code == 200
    assert metadata()[key] == raw
    shown = preview(client, culture['id'], later['id'])
    assert 'deleted_activity_dependency' in shown['blockers']
    assert shown['keep_later']['can_delete']
    before = physical_rows()
    assert delete(client, culture['id'], later['id'], shown).status_code == 409
    assert physical_rows() == before and selected['id'] not in before['logs']
    assert keep_later(client, culture['id'], later['id'], shown).status_code == 200
    assert selected['id'] not in physical_rows()['logs']
