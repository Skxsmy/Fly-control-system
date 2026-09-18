"""A schedule migration must not turn an otherwise safe physical undo into a conflict."""
from datetime import datetime
import json

import pytest

from backend import app as module
from backend.test_activity_cleanup import delete, preview
from backend.test_review import edit
from backend.test_workflows import new_culture, state, workflow_client
from backend.timing import calendar_day_target


@pytest.fixture
def legacy_stock(workflow_client, tmp_path, monkeypatch):
    client, clock = workflow_client
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    current_generator = module.generated_events

    def legacy_generator(container, temperatures):
        events = current_generator(container, temperatures)
        for event in events:
            if event['kind'] == 'stock':
                event.pop('all_day', None)
                event.pop('open_ended', None)
                due = calendar_day_target(module.start_of(container), container['template']['stock_interval'])
                event['due'] = event['end'] = due.replace(hour=9).isoformat(timespec='minutes')
        return events

    monkeypatch.setattr(module, 'generated_events', legacy_generator)

    def migrate(entry='startup'):
        monkeypatch.setattr(module, 'generated_events', current_generator)
        with module.database() as db:
            db.execute("DELETE FROM meta WHERE key='stock_renewal_day10_v1'")
        if entry == 'startup':
            module.init_db()
        else:
            state(client)

    return client, clock, migrate


def current(cid):
    with module.database() as db:
        return module.get_container(db, cid)


def action(client, culture, name, at):
    response = client.post(f'/api/containers/{culture["id"]}/actions', json={'action': name, 'at': at})
    assert response.status_code == 200, response.text
    with module.database() as db:
        return next(log for log in reversed(module.logs_of(db, culture['id'])) if log['action'] == name)


def stock_event(cid):
    with module.database() as db:
        return json.loads(db.execute("SELECT payload FROM events WHERE container_id=? AND rule_key='stock'", (cid,)).fetchone()[0])


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('entry', ['startup', 'state_after_restore'])
def test_old_remove_parents_remains_undoable_after_default_migration(legacy_stock, kind, entry):
    client, _, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', kind=kind,
                          template={'stock_interval': 11})
    removal = action(client, culture, 'remove', '2026-09-01T10:00')
    assert preview(client, culture['id'], removal['id'])['can_delete']
    old_event = stock_event(culture['id'])
    assert old_event['due'] == '2026-09-12T09:00' and not old_event.get('open_ended')

    migrate(entry)
    shown = preview(client, culture['id'], removal['id'])
    assert shown['can_delete'], shown
    assert current(culture['id'])['template']['stock_interval'] == 10
    response = delete(client, culture['id'], removal['id'], shown)
    assert response.status_code == 200, response.text
    restored = current(culture['id'])
    assert restored['parents'] == 'present' and restored['template']['stock_interval'] == 10
    updated = stock_event(culture['id'])
    assert updated['id'] == old_event['id']
    assert updated['due'] == '2026-09-11T00:00' and updated['all_day'] and updated['open_ended']


@pytest.mark.parametrize('interval', [11, 14])
def test_activation_journal_rebases_both_pending_event_versions_using_their_own_anchors(legacy_stock, interval):
    client, clock, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', setup_date='2026-09-03',
                          setup_time='21:00', template={'stock_interval': interval})
    original = stock_event(culture['id'])
    clock['now'] = datetime(2026, 9, 4, 22)
    activation = action(client, culture, 'activate', '2026-09-04T21:07')
    assert preview(client, culture['id'], activation['id'])['can_delete']
    migrate()
    # Normal state reconciliation must serialize the same baseline as migration.
    state(client)
    shown = preview(client, culture['id'], activation['id'])
    assert shown['can_delete'], shown
    response = delete(client, culture['id'], activation['id'], shown)
    assert response.status_code == 200, response.text
    restored = current(culture['id'])
    assert (restored['status'], restored['setup_date'], restored['setup_time']) == ('planned', '2026-09-03', '21:00')
    target_interval = 10 if interval == 11 else interval
    assert restored['template']['stock_interval'] == target_interval
    event = stock_event(culture['id'])
    assert event['id'] == original['id'] and event['open_ended']
    assert event['due'] == calendar_day_target(datetime(2026, 9, 3, 21), target_interval).isoformat(timespec='minutes')


@pytest.mark.parametrize('when', ['before_migration', 'after_migration'])
def test_real_later_notes_edit_still_blocks_undo(legacy_stock, when):
    client, _, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', template={'stock_interval': 11})
    removal = action(client, culture, 'remove', '2026-09-01T10:00')
    if when == 'after_migration':
        migrate()
    assert edit(client, current(culture['id']), notes='Actual later researcher edit').status_code == 200
    if when == 'before_migration':
        assert not preview(client, culture['id'], removal['id'])['can_delete']
        migrate()
    shown = preview(client, culture['id'], removal['id'])
    assert not shown['can_delete'] and 'changed_record' in shown['blockers']
    assert current(culture['id'])['notes'] == 'Actual later researcher edit'


def test_real_later_manual_renewal_reschedule_still_blocks_activation_undo(legacy_stock):
    client, clock, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', setup_date='2026-09-03',
                          template={'stock_interval': 11})
    clock['now'] = datetime(2026, 9, 4, 22)
    activation = action(client, culture, 'activate', '2026-09-04T21:07')
    event = stock_event(culture['id'])
    response = client.patch(f'/api/events/{event["id"]}', json={
        'due': '2026-09-30T14:00', 'end': '2026-09-30T15:00',
    })
    assert response.status_code == 200, response.text
    migrate()
    shown = preview(client, culture['id'], activation['id'])
    assert not shown['can_delete'] and 'changed_record' in shown['blockers']
    moved = stock_event(culture['id'])
    assert moved['pinned'] and moved['due'] == '2026-09-30T14:00' and moved['open_ended']


def test_later_template_edit_cannot_be_hidden_by_a_migration_value_collision(legacy_stock):
    client, _, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', template={'stock_interval': 10})
    removal = action(client, culture, 'remove', '2026-09-01T10:00')
    assert preview(client, culture['id'], removal['id'])['can_delete']
    actual = current(culture['id'])
    assert edit(client, actual, template={**actual['template'], 'stock_interval': 11}).status_code == 200
    assert not preview(client, culture['id'], removal['id'])['can_delete']
    migrate()
    # Live 11 and journal 10 would otherwise both become 10 and incorrectly match.
    assert current(culture['id'])['template']['stock_interval'] == 10
    shown = preview(client, culture['id'], removal['id'])
    assert not shown['can_delete'] and shown['blockers'] == ['changed_record']
    assert shown['keep_later']['can_delete']


def test_migration_keeps_unrelated_metadata_and_is_idempotent(legacy_stock):
    client, _, migrate = legacy_stock
    culture = new_culture(client, purpose='stock', genotype='w1118', template={'stock_interval': 11})
    action(client, culture, 'remove', '2026-09-01T10:00')
    untouched = {
        'activity_deleted:old-log': '{"deleted":true}',
        'activity_undo:invalid-record': '{"invalid":"journal"}',
        'unrelated-metadata': 'keep this exact value',
    }
    with module.database() as db:
        for key, value in untouched.items():
            db.execute('INSERT INTO meta VALUES(?,?)', (key, value))
    migrate()
    with module.database() as db:
        after = list(db.iterdump())
        for key, value in untouched.items():
            assert db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()[0] == value
    module.init_db()
    with module.database() as db:
        assert list(db.iterdump()) == after
