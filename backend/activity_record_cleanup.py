"""Explicit activity-record deletion while retaining recorded physical work.

This path does not execute undo-journal instructions. It removes the selected
log and only its identifiable owning undo metadata. Other records stay intact.
"""
import hashlib
import json

from fastapi import HTTPException

from . import activity_cleanup
from .container_cleanup import _backup_before_delete


DELETED_PREFIX = 'activity_deleted:'


def _journals(db):
    return [dict(row) for row in db.execute(
        "SELECT key,value FROM meta WHERE key LIKE 'activity_undo:%' OR key LIKE 'activity_deleted:%' ORDER BY key")]


def _decode(value):
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _record_plan(db, cid, lid):
    state = activity_cleanup.snapshot(db)
    if cid not in state['containers']:
        raise HTTPException(404, 'container_not_found')
    selected = state['logs'].get(lid)
    if selected is None or selected['container_id'] != cid:
        raise HTTPException(404, 'activity_not_found')
    journals = _journals(db)
    owning_keys, companion_ids = [], set()
    for row in journals:
        if not row['key'].startswith(activity_cleanup.PREFIX):
            continue
        journal = _decode(row['value'])
        log_ids = journal.get('log_ids') if journal else None
        same_group = (journal and journal.get('container_id') == cid
                      and isinstance(log_ids, list)
                      and all(isinstance(item, str) for item in log_ids) and lid in log_ids)
        # The exact key remains identifiable even if an imported journal is
        # invalid or oversized. Never follow its stored write instructions.
        if row['key'] == activity_cleanup.PREFIX + lid or same_group:
            owning_keys.append(row['key'])
            if same_group:
                companion_ids.update(item for item in log_ids if item != lid and item in state['logs'])
    blockers = ['container_creation'] if selected['action'] == 'created' else []
    effects = ['remove_activity', 'keep_recorded_work']
    if selected['action'] == 'clear':
        effects.append('recalculate_virgin_clock')
    if companion_ids:
        effects.append('forget_group_undo')
    fingerprint = hashlib.sha256(json.dumps(
        {'state': state, 'journals': journals, 'container_id': cid, 'activity_id': lid},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode()).hexdigest()
    return {'can_delete': not blockers, 'effects': effects, 'blockers': blockers,
            'fingerprint': fingerprint}, owning_keys


def _restores_deleted_log(db, cid, lid):
    _, journal, error = activity_cleanup._find_journal(db, cid, lid)
    if error or not journal or journal.get('unavailable'):
        return False
    deleted = {row['key'][len(DELETED_PREFIX):] for row in _journals(db)
               if row['key'].startswith(DELETED_PREFIX)}
    return any(change['table'] == 'logs' and change['id'] in deleted
               and change['before'] is not None for change in journal['changes'])


def preview_activity_deletion(db, cid, lid, services=None):
    preview = activity_cleanup.preview_activity_deletion(db, cid, lid, services)
    if _restores_deleted_log(db, cid, lid):
        preview['blockers'] = list(dict.fromkeys([*preview['blockers'], 'deleted_activity_dependency']))
        preview['can_delete'] = False
    preview['keep_later'] = _record_plan(db, cid, lid)[0]
    return preview


def require_no_deleted_log_restoration(db, cid, lid):
    if _restores_deleted_log(db, cid, lid):
        raise HTTPException(409, 'activity_deletion_blocked')


def delete_activity_record(db, cid, lid, fingerprint, backup_dir):
    if not db.in_transaction or db.total_changes:
        raise RuntimeError('Activity deletion requires a fresh BEGIN IMMEDIATE transaction')
    preview, owning_keys = _record_plan(db, cid, lid)
    if fingerprint != preview['fingerprint']:
        raise HTTPException(409, 'activity_preview_changed')
    if not preview['can_delete']:
        raise HTTPException(409, 'activity_deletion_blocked')
    backup = _backup_before_delete(db, backup_dir)
    db.execute('DELETE FROM logs WHERE id=? AND container_id=?', (lid, cid))
    for key in owning_keys:
        db.execute('DELETE FROM meta WHERE key=?', (key,))
    # Keep unrelated journals byte-for-byte intact, but never let their future
    # inverses reinsert an activity the user explicitly deleted.
    db.execute('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO NOTHING',
               (DELETED_PREFIX + lid, json.dumps({'container_id': cid})))
    return {'deleted': lid, 'backup': backup.name, 'mode': 'keep_later'}
