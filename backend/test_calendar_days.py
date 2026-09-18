"""Civil Day labels never replace actual handling or developmental timestamps."""
from datetime import datetime, timedelta, timezone

import pytest

from backend.domain import effective_age, forecast
from backend.test_injection_acceptance import (
    children, collect, current, operate, sole_pending, start_preparation,
)
from backend.test_workflows import new_culture, state, workflow_client
from backend.timing import calendar_day_index, calendar_day_target, elapsed_target


@pytest.mark.parametrize('anchor,at,expected', [
    ('2026-09-01T21:00', '2026-09-01T23:59:59', 0),
    ('2026-09-01T21:00', '2026-09-02T00:00', 1),
    ('2026-09-01T21:00', '2026-09-02T20:59', 1),
    ('2026-09-01T21:00', '2026-09-02T21:00', 1),
    ('2026-09-01T21:00', '2026-09-03T00:00', 2),
    ('2026-09-02T21:00', '2026-09-01T22:00', -1),
    ('2026-12-31T23:59', '2027-01-01T00:00', 1),
    ('2028-02-28T23:59', '2028-03-01T00:00', 2),
])
def test_calendar_day_changes_on_the_local_date_boundary(anchor, at, expected):
    assert calendar_day_index(datetime.fromisoformat(anchor), datetime.fromisoformat(at)) == expected


def test_calendar_target_is_midnight_without_altering_the_actual_anchor():
    anchor = datetime(2026, 9, 1, 21, 17, 32, 456)
    assert calendar_day_target(anchor, 0) == datetime(2026, 9, 1)
    assert calendar_day_target(anchor, 10) == datetime(2026, 9, 11)
    assert elapsed_target(anchor, timedelta(days=10)) == datetime(2026, 9, 11, 21, 17, 32, 456)
    assert anchor == datetime(2026, 9, 1, 21, 17, 32, 456)


def test_calendar_helpers_use_supplied_laboratory_local_dates_not_utc_dates():
    lab_zone = timezone(timedelta(hours=8))
    anchor = datetime(2026, 9, 1, 21, tzinfo=lab_zone)
    midnight = datetime(2026, 9, 2, tzinfo=lab_zone)
    assert calendar_day_index(anchor, midnight) == 1
    assert calendar_day_target(anchor, 1) == midnight
    assert calendar_day_target(anchor, 1).tzinfo == lab_zone


@pytest.mark.parametrize('invalid', [-1, 0.5, True, '1'])
def test_calendar_targets_require_a_nonnegative_whole_day(invalid):
    with pytest.raises(ValueError):
        calendar_day_target(datetime(2026, 9, 1, 21), invalid)


@pytest.mark.parametrize('kind,purpose', [
    ('vial', 'stock'), ('bottle', 'stock'),
    ('egg_laying', 'egg_laying'), ('petri_dish', 'dissection'),
])
@pytest.mark.parametrize('closing_action', [None, 'complete', 'discard'])
def test_all_ordinary_containers_count_midnights_and_keep_setup_time(
        workflow_client, kind, purpose, closing_action):
    client, clock = workflow_client
    clock['now'] = datetime(2026, 9, 1, 21)
    options = {}
    if kind == 'petri_dish':
        options['incubation'] = {
            'lay_start': '2026-09-01T20:00', 'lay_end': '2026-09-01T21:00',
            'min_hours': 24, 'max_hours': 30,
        }
    culture = new_culture(client, kind=kind, purpose=purpose, genotype='w1118',
                          setup_time='21:00', **options)
    assert current(client, culture)['calendar_day'] == 0
    if closing_action:
        clock['now'] = datetime(2026, 9, 1, 22, 7)
        response = client.post(f'/api/containers/{culture["id"]}/actions', json={
            'action': closing_action, 'at': '2026-09-01T22:07',
        })
        assert response.status_code == 200, response.text
    before = current(client, culture)
    clock['now'] = datetime(2026, 9, 2)
    after = current(client, culture)
    assert after['calendar_day'] == 1
    assert (after['setup_date'], after['setup_time']) == ('2026-09-01', '21:00')
    assert after['status'] == before['status']
    assert after['logs'] == before['logs']
    if kind == 'petri_dish':
        assert after['egg_age_hours'] == [3, 4]
        assert after['incubation_window']['start'] == '2026-09-02T20:00'
        assert after['incubation_window']['end'] == '2026-09-03T03:00'


def test_planned_culture_is_not_physically_started_by_midnight(workflow_client):
    client, clock = workflow_client
    culture = new_culture(client, purpose='stock', genotype='w1118',
                          setup_date='2026-09-02', setup_time='21:00')
    assert current(client, culture)['calendar_day'] == -1
    clock['now'] = datetime(2026, 9, 3)
    planned = current(client, culture)
    assert planned['calendar_day'] == 1 and planned['status'] == 'planned'
    clock['now'] = datetime(2026, 9, 3, 0, 7)
    response = client.post(f'/api/containers/{culture["id"]}/actions', json={
        'action': 'activate', 'at': '2026-09-03T00:07',
    })
    assert response.status_code == 200, response.text
    actual = current(client, culture)
    assert actual['calendar_day'] == 0 and actual['setup_time'] == '00:07'


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_cooling_and_warming_change_development_but_never_the_civil_day(workflow_client, kind):
    client, clock = workflow_client
    clock['now'] = datetime(2026, 9, 1, 21)
    culture = new_culture(client, purpose='larvae', genotype='w1118', kind=kind, setup_time='21:00')
    clock['now'] = datetime(2026, 9, 1, 22)
    response = client.post(f'/api/containers/{culture["id"]}/actions', json={
        'action': 'cold', 'at': '2026-09-01T22:00',
    })
    assert response.status_code == 200, response.text
    clock['now'] = datetime(2026, 9, 2)
    cold = current(client, culture)
    assert cold['calendar_day'] == 1
    assert effective_age(cold, cold['temperatures'], clock['now']) == pytest.approx(2 / 24)
    assert forecast(cold, cold['temperatures'], 5) == datetime(2026, 9, 11, 20)
    response = client.post(f'/api/containers/{culture["id"]}/actions', json={
        'action': 'warm', 'at': '2026-09-02T00:00',
    })
    assert response.status_code == 200, response.text
    warm = current(client, culture)
    assert warm['calendar_day'] == 1
    assert forecast(warm, warm['temperatures'], 5) == datetime(2026, 9, 6, 22)
    assert [change['at'] for change in warm['temperatures']] == [
        '2026-09-01T22:00', '2026-09-02T00:00',
    ]


def test_injection_day_opens_at_midnight_and_embryos_keep_exact_minutes(workflow_client):
    client, clock = workflow_client
    source = new_culture(client, purpose='stock', genotype='w1118')
    bottle = start_preparation(client, source)
    awaiting = current(client, bottle)
    assert awaiting['calendar_day'] is None and awaiting['injection_day'] is None

    clock['now'] = datetime(2026, 9, 11, 21)
    collect(client, source, '2026-09-11T21:00')
    assert current(client, bottle)['calendar_day'] == 0
    clock['now'] = datetime(2026, 9, 12)
    active = current(client, bottle)
    assert active['calendar_day'] == 1 and active['injection_day'] == 1
    assert active['injection']['started_at'] == '2026-09-11T21:00'
    transfer = sole_pending(client, bottle, 'injection_transfer')
    assert (transfer['due'], transfer['scheduled_at']) == ('2026-09-15T00:00', '2026-09-15T21:00')
    response = client.patch(f'/api/events/{transfer["id"]}', json={
        'due': '2026-09-15T09:00', 'end': '2026-09-15T11:00',
    })
    assert response.status_code == 200, response.text
    pinned = sole_pending(client, bottle, 'injection_transfer')
    assert pinned['scheduled_at'] == '2026-09-15T21:00'
    assert pinned['due'] == '2026-09-15T09:00' and pinned['pinned']

    clock['now'] = datetime(2026, 9, 14, 23, 59)
    assert children(client, bottle) == []
    clock['now'] = datetime(2026, 9, 15)
    cage = children(client, bottle)[0]
    assert cage['status'] == 'planned' and cage['calendar_day'] == 4
    # Repeated reads and crossing the former elapsed-time threshold never create
    # a second cage or change the reminder identity.
    clock['now'] = datetime(2026, 9, 15, 21, 1)
    assert [child['id'] for child in children(client, bottle)] == [cage['id']]
    assert sole_pending(client, bottle, 'injection_transfer')['id'] == transfer['id']
    operate(client, bottle, 'injection_transfer', '2026-09-15T21:01', event_id=transfer['id'])
    renewal = sole_pending(client, cage, 'injection_renew')
    assert (renewal['due'], renewal['scheduled_at']) == ('2026-09-16T00:00', '2026-09-16T21:00')

    clock['now'] = datetime(2026, 9, 16, 23, 50)
    operate(client, cage, 'injection_renew', '2026-09-16T23:50', event_id=renewal['id'])
    embryos = sole_pending(client, cage, 'injection_embryos')
    assert embryos['due'] == embryos['end'] == '2026-09-17T00:20'
    assert embryos['all_day'] is False and 'scheduled_at' not in embryos
    clock['now'] = datetime(2026, 9, 17)
    after_midnight = current(client, cage)
    assert after_midnight['calendar_day'] == 6
    assert after_midnight['injection']['renewed_at'] == '2026-09-16T23:50'
    assert sole_pending(client, cage, 'injection_embryos')['due'] == '2026-09-17T00:20'
    clock['now'] = datetime(2026, 9, 17, 0, 25)
    operate(client, cage, 'injection_embryos', '2026-09-17T00:25',
            event_id=embryos['id'], continue_collection=True)
    assert sole_pending(client, cage, 'injection_embryos')['due'] == '2026-09-17T00:55'
    actual = current(client, cage)
    assert actual['injection']['renewed_at'] == '2026-09-17T00:25'
    assert actual['setup_time'] == '21:00'
