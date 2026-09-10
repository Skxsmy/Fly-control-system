"""Backed-up correction of recorded physical operations.

New operations store only changed rows, in existing metadata storage.  Undo is
conservative: it never overwrites a subsequently edited row, cascades through a
child culture, or invents a legacy culture's original state.
"""
import hashlib
import json

from fastapi import HTTPException

from .container_cleanup import _backup_before_delete


PREFIX = 'activity_undo:'
COLUMNS = {
    'containers': ('id', 'label', 'payload'),
    'temperatures': ('id', 'container_id', 'at', 'temperature'),
    'logs': ('id', 'container_id', 'at', 'action', 'notes'),
    'events': ('id', 'container_id', 'rule_key', 'payload'),
    'plans': ('id', 'container_id', 'payload'),
    'egg_batches': ('id', 'source_id', 'payload'),
}
STAGES = ['unobserved', 'larvae', 'pupae', 'eclosion', 'first_instar']
PARENTS = ['present', 'removed', 'transferred']


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def snapshot(db):
    return {table: {row['id']: dict(row) for row in db.execute(f'SELECT * FROM {table} ORDER BY rowid')}
            for table in COLUMNS}


def _owner(table, row):
    return row['id'] if table == 'containers' else row['source_id' if table == 'egg_batches' else 'container_id']


def _related(state, cid):
    return [rid for rid, row in state['containers'].items() if json.loads(row['payload']).get('source_id') == cid]


def record(db, before, cid):
    """Finish an operation inside the same transaction as its physical changes."""
    after = snapshot(db)
    log_ids = [rid for rid, row in after['logs'].items()
               if rid not in before['logs'] and row['container_id'] == cid]
    if not log_ids:
        return
    changes = []
    for table in COLUMNS:
        for rid in before[table].keys() | after[table].keys():
            old, new = before[table].get(rid), after[table].get(rid)
            if old != new:
                changes.append({'table': table, 'id': rid, 'before': old, 'after': new})
    journal = {'version': 1, 'container_id': cid, 'log_ids': log_ids,
               'known_log_ids': [rid for rid, row in after['logs'].items() if row['container_id'] == cid],
               'known_related_ids': _related(after, cid), 'changes': changes}
    raw = _json(journal)
    if len(raw) > 100000:
        raw = _json({'version': 1, 'container_id': cid, 'log_ids': log_ids, 'unavailable': 'journal_too_large'})
    db.execute('INSERT INTO meta(key,value) VALUES(?,?)', (PREFIX + log_ids[-1], raw))


def _row_valid(table, row, rid):
    if not isinstance(row, dict) or set(row) != set(COLUMNS[table]) or row.get('id') != rid:
        return False
    if any(not isinstance(value, (str, int, type(None))) for value in row.values()):
        return False
    if not isinstance(rid, str) or not rid:
        return False
    if 'payload' in row:
        try:
            payload = json.loads(row['payload'])
        except (TypeError, ValueError):
            return False
        if not isinstance(payload, dict) or payload.get('id') != rid:
            return False
        if table == 'containers' and payload.get('label') != row['label']:
            return False
        if table != 'containers' and payload.get('source_id' if table == 'egg_batches' else 'container_id') != _owner(table, row):
            return False
    return True


def validate_journal(journal, key=None):
    """Validate imported journal shape. SQL identifiers always come from COLUMNS."""
    if not isinstance(journal, dict) or journal.get('version') != 1 or not isinstance(journal.get('container_id'), str):
        return False
    for field in ('log_ids',):
        if not isinstance(journal.get(field), list) or not journal[field] or any(not isinstance(v, str) for v in journal[field]):
            return False
    if key is not None and key != PREFIX + journal['log_ids'][-1]:
        return False
    if journal.get('unavailable') == 'journal_too_large':
        return True
    for field in ('known_log_ids', 'known_related_ids'):
        if not isinstance(journal.get(field), list) or any(not isinstance(v, str) for v in journal[field]):
            return False
    changes = journal.get('changes')
    if not isinstance(changes, list) or len(changes) > 2000:
        return False
    seen = set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != {'table', 'id', 'before', 'after'}:
            return False
        table, rid = change['table'], change['id']
        if not isinstance(table, str) or table not in COLUMNS or not isinstance(rid, str) or (table, rid) in seen:
            return False
        seen.add((table, rid))
        old, new = change['before'], change['after']
        if old is None and new is None:
            return False
        for row in (old, new):
            if row is not None and not _row_valid(table, row, rid):
                return False
        if old is not None and new is not None and _owner(table, old) != _owner(table, new):
            return False
    return True


def _find_journal(db, cid, lid):
    found = []
    for row in db.execute("SELECT key,value FROM meta WHERE key LIKE 'activity_undo:%'"):
        try:
            journal = json.loads(row['value'])
        except (TypeError, ValueError):
            if row['key'] == PREFIX + lid:
                return row['key'], None, 'invalid_journal'
            continue
        if row['key'] == PREFIX + lid and (not isinstance(journal, dict) or journal.get('container_id') != cid):
            return row['key'], None, 'invalid_journal'
        if isinstance(journal, dict) and journal.get('container_id') == cid:
            log_ids = journal.get('log_ids')
            if row['key'] == PREFIX + lid or (isinstance(log_ids, list) and lid in log_ids):
                found.append((row['key'], journal))
    if len(found) > 1:
        return None, None, 'invalid_journal'
    if not found:
        return None, None, None
    key, journal = found[0]
    if not validate_journal(journal, key):
        return key, None, 'invalid_journal'
    return key, journal, None


def _change(table, before, after):
    return {'table': table, 'id': (before or after)['id'], 'before': before, 'after': after}


def _event_row(row, payload):
    return {**row, 'payload': json.dumps(payload, ensure_ascii=False)}


def _journal_plan(state, cid, lid, journal):
    blockers, changes, effects = [], [], ['remove_activity']
    if journal.get('unavailable'):
        return [], effects, [journal['unavailable']]
    current = json.loads(state['containers'][cid]['payload'])
    source_id = current.get('source_id')
    inserted_children = {}
    for change in journal['changes']:
        if change['table'] == 'containers' and change['before'] is None and change['after'] is not None:
            child = json.loads(change['after']['payload'])
            if child.get('source_id') != cid or change['id'] == cid:
                return [], effects, ['invalid_journal']
            inserted_children[change['id']] = child
    # Journals are data, including after restore. Constrain their write scope.
    for change in journal['changes']:
        table, rid = change['table'], change['id']
        row = change['after'] or change['before']
        owner = _owner(table, row)
        if owner != cid:
            if owner in inserted_children and change['before'] is None:
                if owner in state['containers']:
                    blockers.append('linked_container')
                elif rid in state[table]:
                    blockers.append('changed_record')
                continue
            if not (table == 'logs' and owner == source_id and change['before'] is None
                    and row['action'] in ('egg_laying_parents', 'egg_laying_offspring')
                    and row['notes'] == current['label']):
                return [], effects, ['invalid_journal']
        now = state[table].get(rid)
        if now != change['after']:
            blockers.append('changed_record')
        changes.append(change)
        if table == 'temperatures':
            effects.append('restore_temperature')
        elif table == 'containers':
            effects.append('restore_container_state')
        elif table == 'events':
            effects.append('restore_reminders')
        elif table == 'egg_batches':
            effects.append('restore_egg_batch')
    inserted_logs = {change['id'] for change in changes if change['table'] == 'logs' and change['before'] is None and change['after']['container_id'] == cid}
    if set(journal['log_ids']) != inserted_logs or lid not in inserted_logs:
        return [], effects, ['invalid_journal']
    if any(row['container_id'] == cid and rid not in journal['known_log_ids'] for rid, row in state['logs'].items()):
        blockers.append('later_activity')
    if any(rid not in journal['known_related_ids'] for rid in _related(state, cid)):
        blockers.append('linked_container')
    return changes, effects, list(dict.fromkeys(blockers))


def _legacy_plan(state, cid, lid):
    log = state['logs'][lid]
    action = log['action']
    current_row = state['containers'][cid]
    current = json.loads(current_row['payload'])
    restored = dict(current)
    changes = [_change('logs', None, log)]
    effects, blockers, corrections, reminders = ['remove_activity'], [], [], []
    logs = [row for row in state['logs'].values() if row['container_id'] == cid]
    position = next(i for i, row in enumerate(logs) if row['id'] == lid)
    if any(row['action'] != 'created' for row in logs[position + 1:]):
        blockers.append('later_activity')
    if action == 'created':
        blockers.append('container_creation')
    elif action in ('transfer', 'generation', 'egg_laying_parents', 'egg_laying_offspring', 'egg_laying_transfer', 'egg_laying_generation'):
        blockers.append('linked_history_required')
    elif action.startswith('egg_'):
        blockers.append('linked_egg_batch')
    elif action in ('activate', 'setup_planned'):
        blockers.append('setup_history_required')
    elif action in ('cold', 'warm'):
        matches = [row for row in state['temperatures'].values() if row['container_id'] == cid and row['at'] == log['at'] and row['temperature'] == (18 if action == 'cold' else 25)]
        if len(matches) != 1:
            blockers.append('temperature_record_missing')
        else:
            changes.append(_change('temperatures', None, matches[0]))
            effects.append('restore_temperature')
    elif action == 'remove':
        if current['parents'] != 'removed':
            blockers.append('changed_record')
        restored['parents'] = 'present'
        effects.append('restore_container_state')
    elif action == 'clear':
        corrections.append({'field': 'parents', 'options': PARENTS})
        effects.extend(['restore_container_state', 'restore_virgin_clock'])
    elif action in ('larvae', 'pupae', 'eclosion', 'first_instar'):
        corrections.append({'field': 'stage', 'options': STAGES})
        if current['stage'] != action:
            blockers.append('changed_record')
        if action == 'eclosion':
            remaining = [row['at'] for row in logs if row['id'] != lid and row['action'] == 'eclosion']
            if current.get('first_eclosion_at') == log['at']:
                if remaining:
                    restored['first_eclosion_at'] = min(remaining)
                else:
                    restored.pop('first_eclosion_at', None)
        effects.append('restore_container_state')
    elif action in ('complete', 'discard'):
        if current['status'] != ('completed' if action == 'complete' else 'discarded'):
            blockers.append('changed_record')
        restored['status'] = 'active'
        effects.extend(['restore_container_state', 'restore_reminders'])
        if any(row['source_id'] == cid and json.loads(row['payload'])['status'] == 'cancelled' for row in state['egg_batches'].values()):
            blockers.append('egg_batch_history_required')
        for row in state['events'].values():
            event = json.loads(row['payload'])
            if row['container_id'] == cid and event['status'] == 'cancelled' and event.get('cancel_reason') == 'container_closed':
                event['status'] = 'pending'
                event.pop('cancel_reason', None)
                changes.append(_change('events', _event_row(row, event), row))
    elif action not in ('collect', 'tissue', 'dissect', 'image', 'score', 'third_instar'):
        blockers.append('unsupported_activity')
    if restored != current:
        changes.append(_change('containers', {**current_row, 'payload': json.dumps(restored, ensure_ascii=False)}, current_row))
    # A legacy completion has no event ID. Present candidates; never guess which
    # completed task (including rescheduled tasks) belonged to this operation.
    for row in state['events'].values():
        event = json.loads(row['payload'])
        kind = {'watch': 'eclosion', 'egg_setup': 'activate'}.get(event['kind'], event['kind'])
        if row['container_id'] == cid and event['status'] == 'done' and kind == action:
            reminders.append({key: event.get(key, '') for key in ('id', 'kind', 'due', 'end', 'title')})
    if reminders:
        effects.append('choose_reminders')
    return changes, effects, list(dict.fromkeys(blockers)), corrections, reminders


def _validate_projection(db, changes, journal_key, services):
    """Imported undo metadata must not smuggle invalid records into the workspace."""
    from .workspace_restore import _read_rows, _validate_records
    rows = _read_rows(db)
    for change in changes:
        table, rid, previous = change['table'], change['id'], change['before']
        rows[table] = [row for row in rows[table] if row['id'] != rid]
        if previous is not None:
            rows[table].append(previous)
    if journal_key:
        rows['meta'] = [row for row in rows['meta'] if row['key'] != journal_key]
    try:
        _validate_records(rows, services)
    except (HTTPException, ValueError, TypeError, KeyError, AttributeError) as error:
        raise HTTPException(409, 'activity_restoration_invalid') from error


def _plan(db, cid, lid, services=None):
    state = snapshot(db)
    if cid not in state['containers']:
        raise HTTPException(404, 'container_not_found')
    if lid not in state['logs'] or state['logs'][lid]['container_id'] != cid:
        raise HTTPException(404, 'activity_not_found')
    key, journal, error = _find_journal(db, cid, lid)
    if error:
        changes, effects, blockers, corrections, reminders = [], [], [error], [], []
    elif journal:
        changes, effects, blockers = _journal_plan(state, cid, lid, journal)
        corrections, reminders = [], []
    else:
        changes, effects, blockers, corrections, reminders = _legacy_plan(state, cid, lid)
    if journal and not blockers and services is not None:
        try:
            _validate_projection(db, changes, key, services)
        except HTTPException:
            blockers.append('invalid_journal')
    related = [row for row in state['logs'].values() if journal and row['id'] in journal['log_ids'] and row['id'] != lid]
    fingerprint = hashlib.sha256(_json({'state': state, 'journal_key': key, 'journal': journal, 'activity': lid}).encode()).hexdigest()
    preview = {'fingerprint': fingerprint, 'effects': list(dict.fromkeys(effects)), 'blockers': blockers,
               'can_delete': not blockers, 'corrections': corrections, 'reminders': reminders,
               'related_activities': [{key: row[key] for key in ('id', 'action', 'at')} for row in related],
               'legacy': journal is None}
    return preview, changes, state, key


def preview_activity_deletion(db, cid, lid, services=None):
    return _plan(db, cid, lid, services)[0]


def delete_activity(db, cid, lid, fingerprint, corrections, reopen_event_ids, backup_dir, reconcile, get_container, services=None):
    if not db.in_transaction or db.total_changes:
        raise RuntimeError('Activity deletion requires a fresh BEGIN IMMEDIATE transaction')
    preview, changes, state, journal_key = _plan(db, cid, lid, services)
    if fingerprint != preview['fingerprint']:
        raise HTTPException(409, 'activity_preview_changed')
    if preview['blockers']:
        raise HTTPException(409, 'activity_deletion_blocked')
    required = {item['field']: item['options'] for item in preview['corrections']}
    if set(corrections) != set(required) or any(value not in required[field] for field, value in corrections.items()):
        raise HTTPException(422, 'activity_correction_required')
    candidates = {item['id'] for item in preview['reminders']}
    if len(set(reopen_event_ids)) != len(reopen_event_ids) or not set(reopen_event_ids) <= candidates:
        raise HTTPException(422, 'activity_reminder_invalid')
    if corrections:
        item = next((change for change in changes if change['table'] == 'containers'), None)
        before = item['before'] if item else state['containers'][cid]
        payload = json.loads(before['payload'])
        payload.update(corrections)
        corrected = {**before, 'payload': json.dumps(payload, ensure_ascii=False)}
        if item:
            item['before'] = corrected
        else:
            changes.append(_change('containers', corrected, state['containers'][cid]))
    for eid in reopen_event_ids:
        row = state['events'][eid]
        event = json.loads(row['payload'])
        event['status'] = 'pending'
        changes.append(_change('events', _event_row(row, event), row))
    if services is not None:
        _validate_projection(db, changes, journal_key, services)
    backup = _backup_before_delete(db, backup_dir)
    # Child creation is a blocker, so undo never inserts/deletes containers.
    for change in changes:
        table, rid, previous = change['table'], change['id'], change['before']
        if previous is None:
            db.execute(f'DELETE FROM {table} WHERE id=?', (rid,))
        else:
            columns = COLUMNS[table]
            updates = ','.join(f'{column}=excluded.{column}' for column in columns if column != 'id')
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)}) ON CONFLICT(id) DO UPDATE SET {updates}",
                       tuple(previous[column] for column in columns))
    if journal_key:
        db.execute('DELETE FROM meta WHERE key=?', (journal_key,))
    reconcile(db, get_container(db, cid))
    return {'deleted': lid, 'backup': backup.name}
