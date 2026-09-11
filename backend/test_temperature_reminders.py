"""Actual cold/warm handling reforecasts existing tube reminders without resetting age."""
from datetime import datetime

import pytest

from backend.test_workflows import workflow_client, new_culture, state, events_for


def record_temperature(client, clock, culture, action, at):
    clock['now'] = datetime.fromisoformat(at)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': action, 'at': at,
    })
    assert response.status_code == 200, response.text
    return state(client)


def indexed_events(client, culture):
    events = events_for(client, culture)
    assert len({event['rule_key'] for event in events}) == len(events)
    return {event['id']: event for event in events}


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('purpose,workflow,expected', [
    ('virgin', {}, {
        'check': ('09-07', '09-11', '09-08'),
        'watch': ('09-10', '09-17', '09-11'),
        'collect': ('09-11', '09-19', '09-12'),
    }),
    ('cross', {'cross_goal': 'score'}, {
        'check': ('09-07', '09-11', '09-08'),
        'watch': ('09-10', '09-17', '09-11'),
        'score': ('09-11', '09-19', '09-12'),
    }),
    ('larvae', {}, {'third_instar': ('09-06', '09-09', '09-07')}),
    ('cross', {'cross_goal': 'third_instar'}, {
        'third_instar': ('09-06', '09-09', '09-07'),
    }),
    ('stock', {}, {'check': ('09-07', '09-11', '09-08')}),
])
def test_cold_delays_and_actual_warm_advances_existing_development_reminders(
    workflow_client, kind, purpose, workflow, expected,
):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, purpose=purpose, genotype='w1118',
                          setup_time='09:00', workflow=workflow)
    original = indexed_events(client, culture)
    record_temperature(client, clock, culture, 'cold', '2026-09-03T09:00')
    cold = indexed_events(client, culture)

    # Opening the application later cannot fabricate a return to 25°C.
    clock['now'] = datetime(2026, 9, 5, 9)
    assert indexed_events(client, culture) == cold
    cold_culture = next(item for item in state(client)['containers'] if item['id'] == culture['id'])
    assert cold_culture['temperature'] == 18
    assert cold_culture['calendar_day'] == 4
    assert cold_culture['effective_age'] == 3

    record_temperature(client, clock, culture, 'warm', '2026-09-05T09:00')
    warm = indexed_events(client, culture)
    assert original.keys() == cold.keys() == warm.keys()
    assert indexed_events(client, culture) == warm

    observed_kinds = set()
    for event_id, initial in original.items():
        chilled, returned = cold[event_id], warm[event_id]
        event_kind = 'check' if initial['kind'] == 'tissue' else initial['kind']
        if event_kind in expected:
            observed_kinds.add(event_kind)
            dates = expected[event_kind]
            for event, date in zip((initial, chilled, returned), dates):
                assert event['due'][:10] == f'2026-{date}'
                assert event['end'][:10] == f'2026-{date}'
                assert event['basis'] == 'development'
                assert event['status'] == 'pending' and not event['pinned']
                assert event['due'][11:] == initial['due'][11:]
                assert event['end'][11:] == initial['end'][11:]
            # Warming shortens the cold forecast, but never erases time already spent cold.
            assert initial['due'] < returned['due'] < chilled['due']
        else:
            assert initial['kind'] in ('transfer', 'remove', 'stock')
            assert (chilled['due'], chilled['end']) == (initial['due'], initial['end'])
            assert (returned['due'], returned['end']) == (initial['due'], initial['end'])
    assert observed_kinds == set(expected)
    if purpose == 'virgin':
        collection = [event for event in warm.values() if event['kind'] == 'collect']
        assert len(collection) == 3
        assert {event['due'] for event in collection} == {
            '2026-09-12T09:00', '2026-09-12T15:00', '2026-09-12T19:00',
        }


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_multiple_partial_day_cold_intervals_accumulate_before_warm_reforecast(
    workflow_client, kind,
):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, purpose='larvae', genotype='w1118',
                          setup_time='09:15')
    original = events_for(client, culture, 'third_instar')[0]
    operations = [
        ('cold', '2026-09-02T15:15'),
        ('warm', '2026-09-03T09:45'),
        ('cold', '2026-09-04T03:15'),
    ]
    for action, at in operations:
        record_temperature(client, clock, culture, action, at)
    second_cold = events_for(client, culture, 'third_instar')[0]
    assert second_cold['due'] == '2026-09-09T09:00'
    data = record_temperature(client, clock, culture, 'warm', '2026-09-04T17:45')
    returned = events_for(client, culture, 'third_instar')[0]
    assert returned['id'] == second_cold['id'] == original['id']
    assert (returned['due'], returned['end']) == ('2026-09-07T09:00', '2026-09-07T17:00')
    updated = next(item for item in data['containers'] if item['id'] == culture['id'])
    assert updated['temperature'] == 25
    assert updated['effective_age'] == 2.7  # The API displays days to one decimal place.
    # 18.5 h + 14.5 h at half speed retain exactly 16.5 h of developmental delay.
    assert updated['eclosion_estimate']['at'] == '2026-09-12T01:45'
    assert [(item['at'], item['temperature']) for item in updated['temperatures']] == [
        ('2026-09-02T15:15', 18), ('2026-09-03T09:45', 25),
        ('2026-09-04T03:15', 18), ('2026-09-04T17:45', 25),
    ]


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('override', ['pinned', 'done', 'skipped', 'disabled'])
def test_larval_manual_overrides_and_history_survive_both_temperature_moves(
    workflow_client, kind, override,
):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, purpose='larvae', genotype='w1118', setup_time='09:00')
    initial = events_for(client, culture, 'third_instar')[0]
    payload = ({'due': '2026-09-08T13:15', 'end': '2026-09-08T14:45'}
               if override == 'pinned' else {'status': override})
    response = client.patch(f"/api/events/{initial['id']}", json=payload)
    assert response.status_code == 200, response.text
    preserved = events_for(client, culture, 'third_instar')[0]
    custom_response = client.post('/api/events', json={
        'container_id': culture['id'], 'title': 'Prepare dissection tools',
        'due': '2026-09-07T16:00', 'end': '2026-09-07T16:30',
    })
    assert custom_response.status_code == 200, custom_response.text
    custom = next(event for event in events_for(client, culture) if event['title'] == 'Prepare dissection tools')
    for action, at in [('cold', '2026-09-03T09:00'), ('warm', '2026-09-05T09:00')]:
        record_temperature(client, clock, culture, action, at)
        assert events_for(client, culture, 'third_instar') == [preserved]
        assert indexed_events(client, culture)[custom['id']] == custom


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_cooling_after_a_stage_was_reached_does_not_move_its_overdue_reminder(
    workflow_client, kind,
):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, purpose='virgin', genotype='w1118', setup_time='09:00')
    check_kind = 'tissue' if kind == 'bottle' else 'check'
    original = events_for(client, culture, check_kind)[0]
    record_temperature(client, clock, culture, 'cold', '2026-09-08T09:00')
    assert events_for(client, culture, check_kind) == [original]
    assert events_for(client, culture, 'watch')[0]['due'] == '2026-09-12T09:00'
    record_temperature(client, clock, culture, 'warm', '2026-09-10T09:00')
    assert events_for(client, culture, check_kind) == [original]
    assert events_for(client, culture, 'watch')[0]['due'] == '2026-09-11T09:00'


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_observed_eclosion_remains_the_anchor_for_follow_eclosion_scoring(
    workflow_client, kind,
):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, setup_time='09:00', workflow={
        'cross_goal': 'score', 'follow_eclosion': True,
    })
    clock['now'] = datetime(2026, 9, 8, 15)
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': 'eclosion', 'at': '2026-09-08T14:30',
    })
    assert response.status_code == 200, response.text
    observed_score = events_for(client, culture, 'score')[0]
    assert observed_score['due'] == '2026-09-08T09:00'
    for action, at in [('cold', '2026-09-09T09:00'), ('warm', '2026-09-10T09:00')]:
        data = record_temperature(client, clock, culture, action, at)
        assert events_for(client, culture, 'score') == [observed_score]
        updated = next(item for item in data['containers'] if item['id'] == culture['id'])
        assert updated['eclosion_estimate']['at'] == '2026-09-08T14:30'
        assert updated['eclosion_estimate']['basis'] == 'observed'
