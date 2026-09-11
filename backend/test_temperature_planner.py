"""L3 cooling plans use the selected stage and remain distinct from actual moves."""
from copy import deepcopy
from datetime import datetime

import pytest

from backend.domain import (
    DEFAULT_SETTINGS, DEFAULT_TEMPLATE, available, event_conflict,
    forecast, parse, suggest_cooling,
)
from backend.test_workflows import workflow_client, new_culture, state


def larval_input(kind, purpose, day=5):
    return {
        'id': 'isolated-domain-culture', 'kind': kind, 'purpose': purpose,
        'setup_date': '2026-09-01', 'setup_time': '09:00',
        'initial_temperature': 25, 'status': 'active', 'parents': 'removed',
        'transfer_index': 0, 'temperature_policy': 'allowed',
        'template': deepcopy(DEFAULT_TEMPLATE),
        'workflow': {'transfer_enabled': False, 'cross_goal': 'third_instar',
                     'third_instar_day': day, 'third_instar_window': ['09:00', '17:00']},
    }


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('purpose', ['larvae', 'cross'])
def test_l3_plan_reports_actual_target_and_ignores_unrelated_eclosion_day(kind, purpose):
    culture = larval_input(kind, purpose)
    settings = deepcopy(DEFAULT_SETTINGS)
    exceptions = [{'date': '2026-09-07', 'windows': []}]
    result = suggest_cooling(culture, [], settings, exceptions, datetime(2026, 9, 3, 9))

    assert result['state'] == 'suggested'
    for option in result['options']:
        projected = [{'at': option['cold_at'], 'temperature': 18},
                     {'at': option['warm_at'], 'temperature': 25}]
        larval_event = next(e for e in option['events'] if e['kind'] == 'third_instar')
        assert option['collection_date'] == larval_event['due'][:10]
        assert larval_event['due'][11:] == '09:00'
        assert larval_event['end'][11:] == '17:00'
        assert not event_conflict(larval_event, settings, exceptions)
        assert available(parse(option['cold_at']), settings, exceptions)
        assert available(parse(option['warm_at']), settings, exceptions)
        # These valid L3 plans used to be rejected by a D9 weekend check.
        assert forecast(culture, projected, 9).weekday() in (5, 6)
        assert option['collection_date'] != forecast(culture, projected, 10).date().isoformat()


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
def test_l3_cutoff_uses_selected_development_day(kind):
    culture = larval_input(kind, 'larvae')
    result = suggest_cooling(culture, [], DEFAULT_SETTINGS, [], datetime(2026, 9, 6, 10))
    assert result == {'state': 'development_target_reached', 'options': []}

    # A later researcher-selected stage is still movable after unrelated D9.
    culture['workflow']['third_instar_day'] = 12
    result = suggest_cooling(culture, [], DEFAULT_SETTINGS, [], datetime(2026, 9, 10, 12))
    assert result['state'] == 'suggested'
    assert all(option['collection_date'] == option['events'][0]['due'][:10]
               for option in result['options'])


@pytest.mark.parametrize('kind', ['vial', 'bottle'])
@pytest.mark.parametrize('purpose', ['larvae', 'cross'])
def test_accepting_l3_plan_waits_for_recorded_cold_and_warm(workflow_client, kind, purpose):
    client, clock = workflow_client
    culture = new_culture(client, kind=kind, purpose=purpose, genotype='w1118',
                          setup_time='09:00', parents='removed',
                          workflow={'cross_goal': 'third_instar', 'transfer_enabled': False})
    clock['now'] = datetime(2026, 9, 3, 9)
    before = state(client)
    original = next(e for e in before['events'] if e['kind'] == 'third_instar')
    response = client.get(f"/api/containers/{culture['id']}/suggestions")
    assert response.status_code == 200, response.text
    assert response.json()['state'] == 'suggested'
    option = response.json()['options'][0]
    response = client.post(f"/api/containers/{culture['id']}/plans", json={
        'cold_at': option['cold_at'], 'warm_at': option['warm_at'],
    })
    assert response.status_code == 200, response.text
    planned = state(client)
    assert planned['containers'][0]['temperatures'] == []
    assert planned['containers'][0]['temperature'] == 25
    assert planned['containers'][0]['logs'] == before['containers'][0]['logs']
    assert next(e for e in planned['events'] if e['id'] == original['id']) == original
    assert {e['kind'] for e in planned['events'] if e['rule_key'].startswith('plan-')} == {'cold', 'warm'}

    clock['now'] = parse(option['cold_at'])
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': 'cold', 'at': option['cold_at'],
    })
    assert response.status_code == 200, response.text
    cold = state(client)
    cold_event = next(e for e in cold['events'] if e['id'] == original['id'])
    assert cold_event['due'] > original['due']

    clock['now'] = parse(option['warm_at'])
    response = client.post(f"/api/containers/{culture['id']}/actions", json={
        'action': 'warm', 'at': option['warm_at'],
    })
    assert response.status_code == 200, response.text
    warmed = state(client)
    warm_event = next(e for e in warmed['events'] if e['id'] == original['id'])
    assert original['due'] < warm_event['due'] < cold_event['due']
    assert warm_event['due'][:10] == option['collection_date']
    assert warm_event['due'] == next(e for e in option['events'] if e['kind'] == 'third_instar')['due']
    assert [t['temperature'] for t in warmed['containers'][0]['temperatures']] == [18, 25]
    assert all(e['status'] == 'done' for e in warmed['events'] if e['rule_key'].startswith('plan-'))
