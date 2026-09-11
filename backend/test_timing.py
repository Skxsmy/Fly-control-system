"""The shared piecewise-rate clock has one consistent forward and inverse model."""
from datetime import datetime, timedelta
from math import inf, nan

import pytest

from backend.timing import RateTimeline, elapsed_target


ORIGIN = datetime(2026, 9, 1, 9, 15)
HOUR = 3600


def at(hours):
    return ORIGIN + timedelta(hours=hours)


def fractional_timeline():
    return RateTimeline(ORIGIN, 1, [
        (at(30), 0.5),
        (at(48.5), 1),
        (at(66), 0.5),
        (at(80.5), 1),
    ])


def test_fractional_hour_transitions_retain_all_prior_rate_intervals():
    timeline = fractional_timeline()
    # 30 h + 18.5 h / 2 + 17.5 h + 14.5 h / 2 = 64 effective hours.
    assert timeline.elapsed_seconds(at(80.5)) == 64 * HOUR
    assert timeline.reaches(120 * HOUR) == datetime(2026, 9, 7, 1, 45)
    assert timeline.reaches(240 * HOUR) == datetime(2026, 9, 12, 1, 45)


def test_custom_rates_use_the_supplied_model_in_both_directions():
    timeline = RateTimeline(ORIGIN, 0.75, [(at(8), 0.25), (at(20), 1.5)])
    assert timeline.elapsed_seconds(at(32)) == 27 * HOUR
    assert timeline.reaches(12 * HOUR) == at(22)
    assert timeline.reaches(24 * HOUR) == at(30)


@pytest.mark.parametrize('hours', [0, 0.25, 29.999, 30, 36, 48.5, 59.125, 66, 70, 80.5, 200])
def test_forward_then_inverse_recovers_boundaries_and_interior_times(hours):
    timeline = fractional_timeline()
    timestamp = at(hours)
    recovered = timeline.reaches(timeline.elapsed_seconds(timestamp))
    assert abs((recovered - timestamp).total_seconds()) <= 0.000001


@pytest.mark.parametrize('effective_hours', [0, 0.125, 30, 34.625, 39.25, 50, 56.75, 64, 120.125])
def test_inverse_then_forward_recovers_the_requested_elapsed_age(effective_hours):
    timeline = fractional_timeline()
    age = effective_hours * HOUR
    assert timeline.elapsed_seconds(timeline.reaches(age)) == pytest.approx(age, abs=0.000001)


def test_splitting_equal_rate_segments_cannot_change_age_or_target_time():
    original = RateTimeline(ORIGIN, 1, [(at(12), 0.5), (at(48), 1)])
    split = RateTimeline(ORIGIN, 1, [
        (at(4), 1), (at(12), 0.5), (at(20), 0.5), (at(40), 0.5),
        (at(48), 1), (at(60), 1),
    ])
    for timestamp in [at(0), at(8), at(12), at(19.5), at(40), at(48), at(72)]:
        assert split.elapsed_seconds(timestamp) == original.elapsed_seconds(timestamp)
    for target in [0, 5 * HOUR, 12 * HOUR, 20.25 * HOUR, 30 * HOUR, 100 * HOUR]:
        assert split.reaches(target) == original.reaches(target)


def test_initial_cold_rate_applies_before_the_first_warm_transition():
    timeline = RateTimeline(ORIGIN, 0.5, [(at(36), 1)])
    assert timeline.elapsed_seconds(at(24)) == 12 * HOUR
    assert timeline.elapsed_seconds(at(36)) == 18 * HOUR
    assert timeline.reaches(24 * HOUR) == at(42)


def test_no_history_extends_initial_rate_and_origin_has_zero_age():
    timeline = RateTimeline(ORIGIN, 0.5)
    assert timeline.elapsed_seconds(at(-100)) == 0
    assert timeline.elapsed_seconds(ORIGIN) == 0
    assert timeline.reaches(0) == ORIGIN
    assert timeline.elapsed_seconds(at(1000)) == 500 * HOUR
    assert timeline.reaches(500 * HOUR) == at(1000)


def test_default_unit_rate_preserves_fixed_calendar_anchors():
    timeline = RateTimeline(ORIGIN)
    for duration in [timedelta(minutes=15), timedelta(hours=30.5), timedelta(days=5), timedelta(days=11)]:
        assert timeline.reaches(duration.total_seconds()) == ORIGIN + duration
        assert timeline.elapsed_seconds(ORIGIN + duration) == duration.total_seconds()


def test_fixed_elapsed_helper_preserves_minutes_and_does_not_reset_the_anchor():
    assert elapsed_target(ORIGIN, timedelta(0)) == ORIGIN
    assert elapsed_target(ORIGIN, timedelta(hours=30, minutes=45)) == datetime(2026, 9, 2, 16)
    assert elapsed_target(ORIGIN, timedelta(days=5)) == datetime(2026, 9, 6, 9, 15)


def test_changes_at_or_before_origin_set_the_initial_rate_without_creating_age():
    timeline = RateTimeline(ORIGIN, 1, [(at(-4), 0.25), (ORIGIN, 0.5), (at(12), 1)])
    assert timeline.elapsed_seconds(at(-1)) == 0
    assert timeline.elapsed_seconds(ORIGIN) == 0
    assert timeline.reaches(0) == ORIGIN
    assert timeline.elapsed_seconds(at(24)) == 18 * HOUR
    assert timeline.reaches(18 * HOUR) == at(24)


def test_later_transitions_do_not_rewrite_targets_already_reached():
    baseline = RateTimeline(ORIGIN, 1, [(at(24), 0.5)])
    extended = RateTimeline(ORIGIN, 1, [(at(24), 0.5), (at(72), 1), (at(96), 0.25)])
    for target in [0, 12 * HOUR, 24 * HOUR, 30 * HOUR, 48 * HOUR]:
        assert extended.reaches(target) == baseline.reaches(target)
    assert extended.elapsed_seconds(at(60)) == baseline.elapsed_seconds(at(60))


def test_input_transition_order_does_not_change_the_chronological_model():
    ordered = [(at(12), 0.5), (at(30), 1.25), (at(50), 0.75)]
    chronological = RateTimeline(ORIGIN, 1, ordered)
    unsorted = RateTimeline(ORIGIN, 1, [ordered[2], ordered[0], ordered[1]])
    assert unsorted.elapsed_seconds(at(90)) == chronological.elapsed_seconds(at(90))
    assert unsorted.reaches(120 * HOUR) == chronological.reaches(120 * HOUR)


@pytest.mark.parametrize('invalid_rate', [0, -0.5, inf, -inf, nan])
def test_invalid_initial_rates_are_rejected(invalid_rate):
    with pytest.raises(ValueError):
        RateTimeline(ORIGIN, invalid_rate)


@pytest.mark.parametrize('invalid_rate', [0, -0.5, inf, -inf, nan])
def test_invalid_transition_rates_are_rejected(invalid_rate):
    with pytest.raises(ValueError):
        RateTimeline(ORIGIN, 1, [(at(24), invalid_rate)])


@pytest.mark.parametrize('invalid_target', [-1, inf, -inf, nan])
def test_invalid_inverse_targets_are_rejected(invalid_target):
    timeline = fractional_timeline()
    with pytest.raises(ValueError):
        timeline.reaches(invalid_target)
