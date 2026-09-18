"""Ongoing stock renewal, actual replacement, and legacy schedule upgrades."""
from copy import deepcopy
from datetime import datetime
import pytest

from backend import app as module
from backend.test_workflows import workflow_client, new_culture, state, events_for


def stock(client, **changes):
    return new_culture(client, **{'purpose': 'stock', 'genotype': 'w1118; UAS-X', **changes})


def renewal(client, culture):
    event, = events_for(client, culture, 'stock')
    return event


def replace(client, source, kind='vial', at='2026-09-15T13:47', **changes):
    day, time = at.split('T')
    return client.post(f"/api/containers/{source['id']}/transfer", json={
        'mode': 'generation', 'kind': kind, 'purpose': 'stock',
        'genotype': source['genotype'], 'setup_date': day, 'setup_time': time,
        **changes,
    })


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_renewal_starts_at_d10_midnight_and_remains_one_ongoing_task(workflow_client, kind):
    client, clock = workflow_client
    clock['now'] = datetime(2026, 9, 1, 21)
    source = stock(client, kind=kind, setup_time='21:00')
    first = renewal(client, source)
    assert source['template']['stock_interval'] == 10
    assert first['due'] == first['end'] == '2026-09-11T00:00'
    assert first['all_day'] and first['open_ended']
    assert not first['critical'] and not first['conflict']
    for at in ['2026-09-11T00:00', '2026-09-12T09:00', '2026-10-01T14:00']:
        clock['now'] = datetime.fromisoformat(at)
        assert renewal(client, source) == first
        assert next(c for c in state(client)['containers'] if c['id'] == source['id'])['status'] == 'active'


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_stock_renewal_calendar_date_survives_actual_cold_and_warm(workflow_client, kind):
    client, clock = workflow_client
    source = stock(client, kind=kind)
    first = renewal(client, source)
    for action, stamp in [('cold', '2026-09-03T21:17'), ('warm', '2026-09-06T08:42')]:
        clock['now'] = datetime.fromisoformat(stamp)
        result = client.post(f"/api/containers/{source['id']}/actions", json={'action': action, 'at': stamp})
        assert result.status_code == 200, result.text
        assert renewal(client, source) == first


@pytest.mark.parametrize('source_kind', ['vial', 'bottle'])
@pytest.mark.parametrize('target_kind', ['vial', 'bottle'])
def test_confirming_renewal_creates_new_cohort_and_discards_source_atomically(
    workflow_client, source_kind, target_kind,
):
    client, clock = workflow_client
    source = stock(client, kind=source_kind, transfer_index=2, parents='removed')
    first = renewal(client, source)
    custom = client.post('/api/events', json={
        'container_id': source['id'], 'title': 'Inspect old culture',
        'due': '2026-09-20T09:00', 'end': '2026-09-20T10:00',
    })
    assert custom.status_code == 200
    clock['now'] = datetime(2026, 9, 15, 13, 47)
    result = replace(client, source, target_kind, genotype='Accidental stale form value')
    assert result.status_code == 200, result.text
    child = result.json()
    assert child['genotype'] == source['genotype']
    assert child['kind'] == target_kind and child['source_id'] == source['id']
    assert child['transfer_index'] == 0 and child['cohort_id'] != source['cohort_id']
    assert child['setup_date'] == '2026-09-15' and child['setup_time'] == '13:47'
    assert child['status'] == 'active'
    current = state(client)
    old = next(c for c in current['containers'] if c['id'] == source['id'])
    assert old['status'] == 'discarded'
    assert old['setup_date'] == source['setup_date'] and old['setup_time'] == source['setup_time']
    action, = [entry for entry in old['logs'] if entry['action'] == 'generation']
    assert action['at'] == '2026-09-15T13:47' and action['notes'] == child['label']
    old_events = events_for(client, source)
    completed = next(e for e in old_events if e['id'] == first['id'])
    assert completed['status'] == 'done'
    assert all(e['status'] != 'pending' for e in old_events)
    cancelled = next(e for e in old_events if e['id'] == custom.json()['id'])
    assert cancelled['status'] == 'cancelled' and cancelled['cancel_reason'] == 'container_closed'
    assert renewal(client, child)['due'] == '2026-09-25T00:00'
    assert replace(client, source, target_kind).status_code == 409
    assert len(state(client)['containers']) == 2


def test_generic_done_cannot_claim_stock_replacement_without_a_new_culture(workflow_client):
    client, _ = workflow_client
    source = stock(client)
    first = renewal(client, source)
    result = client.patch(f"/api/events/{first['id']}", json={'status': 'done'})
    assert result.status_code == 409 and result.json()['detail'] == 'stock_renewal_required'
    assert renewal(client, source) == first
    assert len(state(client)['containers']) == 1


def test_manually_moved_renewal_keeps_its_start_but_never_gets_a_deadline(workflow_client):
    client, clock = workflow_client
    source = stock(client)
    first = renewal(client, source)
    response = client.patch(f"/api/events/{first['id']}", json={
        'due': '2026-09-14T15:17', 'end': '2026-09-14T16:00',
    })
    assert response.status_code == 200, response.text
    clock['now'] = datetime(2026, 9, 20, 9)
    current = renewal(client, source)
    assert current['id'] == first['id'] and current['pinned']
    assert current['due'] == '2026-09-14T15:17' and current['end'] == '2026-09-14T16:00'
    assert current['all_day'] and current['open_ended'] and not current['conflict']
    settings = state(client)['settings']
    settings['template']['stock_interval'] = 12
    assert client.put('/api/settings', json=settings).status_code == 200
    changed = renewal(client, source)
    assert changed['id'] == first['id'] and not changed['pinned']
    assert changed['due'] == '2026-09-13T00:00' and changed['open_ended']


@pytest.mark.parametrize('entry', ['startup', 'state_after_restore'])
def test_legacy_d11_migration_is_bounded_idempotent_and_preserves_manual_and_done_records(workflow_client, entry):
    client, _ = workflow_client
    active = stock(client, template={'stock_interval': 11})
    planned = stock(client, template={'stock_interval': 11}, setup_date='2026-09-20')
    custom = stock(client, template={'stock_interval': 14})
    closed = stock(client, template={'stock_interval': 11})
    pinned = stock(client, template={'stock_interval': 11})
    historical = stock(client, template={'stock_interval': 11})
    cross = new_culture(client, template={'stock_interval': 11})
    assert client.post(f"/api/containers/{closed['id']}/actions", json={
        'action': 'discard', 'at': '2026-09-01T10:00',
    }).status_code == 200
    original = {c['id']: deepcopy(renewal(client, c)) for c in [active, planned, custom, pinned, historical]}
    with module.database() as db:
        settings = module.settings_of(db)
        settings['template']['stock_interval'] = 11
        db.execute("UPDATE meta SET value=? WHERE key='settings'", (module.dump(settings),))
        for culture in [active, planned, custom, pinned, historical]:
            event = original[culture['id']]
            event.pop('open_ended')
            event.pop('all_day')
            event.pop('conflict')
            event['due'] = event['end'] = event['due'][:10] + 'T09:00'
            if culture['id'] == pinned['id']:
                event.update(due='2026-09-25T15:00', end='2026-09-25T16:00', pinned=True)
            if culture['id'] == historical['id']:
                event['status'] = 'done'
            module.save_event(db, event)
        done_row = db.execute('SELECT payload FROM events WHERE id=?', (original[historical['id']]['id'],)).fetchone()[0]
        db.execute("DELETE FROM meta WHERE key='stock_renewal_day10_v1'")
    if entry == 'startup':
        module.init_db()
    after = state(client)
    by_id = {c['id']: c for c in after['containers']}
    assert after['settings']['template']['stock_interval'] == 10
    assert all(by_id[c['id']]['template']['stock_interval'] == 10 for c in [active, planned, pinned, historical])
    assert by_id[custom['id']]['template']['stock_interval'] == 14
    assert by_id[closed['id']]['template']['stock_interval'] == by_id[cross['id']]['template']['stock_interval'] == 11
    for culture, due in [(active, '2026-09-11T00:00'), (planned, '2026-09-30T00:00'), (custom, '2026-09-15T00:00')]:
        current = renewal(client, culture)
        assert current['id'] == original[culture['id']]['id']
        assert current['due'] == due and current['open_ended']
    moved = renewal(client, pinned)
    assert moved['due'] == '2026-09-25T15:00' and moved['pinned'] and moved['open_ended']
    with module.database() as db:
        assert db.execute('SELECT payload FROM events WHERE id=?', (original[historical['id']]['id'],)).fetchone()[0] == done_row
    settings = after['settings']
    settings['template']['stock_interval'] = 11
    assert client.put('/api/settings', json=settings).status_code == 200
    module.init_db()
    assert state(client)['settings']['template']['stock_interval'] == 11
    assert renewal(client, active)['due'] == '2026-09-12T00:00'


def test_failed_renewal_does_not_discard_source_or_complete_event(workflow_client):
    client, clock = workflow_client
    source = stock(client)
    clock['now'] = datetime(2026, 9, 15, 13, 47)
    before = state(client)
    result = replace(client, source, label=source['label'])
    assert result.status_code == 409
    assert state(client) == before


@pytest.mark.parametrize('purpose', ['cross', 'virgin', 'larvae'])
def test_nonstock_next_generation_preserves_source_culture(workflow_client, purpose):
    client, clock = workflow_client
    source = new_culture(client, purpose=purpose, genotype='w1118')
    clock['now'] = datetime(2026, 9, 15, 13, 47)
    result = replace(client, source)
    assert result.status_code == 200, result.text
    current = next(c for c in state(client)['containers'] if c['id'] == source['id'])
    assert current['status'] == 'active' and current['parents'] == source['parents']


def test_renewal_respects_a_previously_disabled_reminder(workflow_client):
    client, clock = workflow_client
    source = stock(client)
    first = renewal(client, source)
    assert client.patch(f"/api/events/{first['id']}", json={'status': 'disabled'}).status_code == 200
    clock['now'] = datetime(2026, 9, 15, 13, 47)
    assert replace(client, source).status_code == 200
    assert renewal(client, source)['status'] == 'disabled'
