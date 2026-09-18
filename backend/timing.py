"""Shared forward/inverse elapsed-time engine, independent of workflow and UI.

Rates express clock progress per second of wall time. A constant rate of 1 is
ordinary elapsed time; a culture timeline uses its configured temperature rates.
Callers supply either recorded history or an explicit hypothetical plan, never
mix the two implicitly. Anchors and protocol targets belong to the caller.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import isfinite
from typing import Iterable


@dataclass(frozen=True)
class _Segment:
    start: datetime
    end: datetime | None
    rate: float


class RateTimeline:
    """Integrate progress and invert it using the same ordered time segments."""

    def __init__(self, origin: datetime, initial_rate: float = 1.0,
                 changes: Iterable[tuple[datetime, float]] = ()):
        def valid_rate(value):
            if not isfinite(value) or value <= 0:
                raise ValueError('Clock rates must be finite and positive')
            return value

        self.origin = origin
        cursor, current = origin, valid_rate(initial_rate)
        segments = []
        for at, value in sorted(changes, key=lambda item: item[0]):
            value = valid_rate(value)
            if at > cursor:
                segments.append(_Segment(cursor, at, current))
                cursor = at
            current = value
        segments.append(_Segment(cursor, None, current))
        self._segments = tuple(segments)

    def elapsed_seconds(self, at: datetime) -> float:
        """Progress since the anchor; later changes cannot affect earlier age."""
        total = 0.0
        for segment in self._segments:
            if at <= segment.start:
                break
            end = min(at, segment.end) if segment.end else at
            total += (end - segment.start).total_seconds() * segment.rate
            if end == at:
                break
        return total

    def reaches(self, elapsed_seconds: float) -> datetime:
        """Earliest time the target progress is reached; last rate continues."""
        if not isfinite(elapsed_seconds) or elapsed_seconds < 0:
            raise ValueError('Clock targets must be finite and nonnegative')
        remaining = elapsed_seconds
        for segment in self._segments:
            progress = ((segment.end - segment.start).total_seconds() * segment.rate
                        if segment.end else None)
            if progress is None or remaining <= progress:
                return segment.start + timedelta(seconds=remaining / segment.rate)
            remaining -= progress
        raise AssertionError('A timeline must have an open final segment')


def elapsed_target(anchor: datetime, duration: timedelta) -> datetime:
    """Fixed elapsed-time target, without a culture temperature conversion."""
    return RateTimeline(anchor).reaches(duration.total_seconds())


def calendar_day_index(anchor: datetime, at: datetime) -> int:
    """Lab-local Day number; midnight advances it without changing actual age.

    Inputs must already use the same laboratory timezone, as other scheduling
    inputs do. A future planned anchor has a negative index. This civil-date
    label is independent of elapsed hours and temperature-adjusted development.
    """
    return (at.date() - anchor.date()).days


def calendar_day_target(anchor: datetime, day: int) -> datetime:
    """Start of calendar Day N in the anchor's lab-local timezone.

    Use this only for a rule explicitly defined by calendar day. Keep exact-hour
    and developmental targets anchored to the original timestamp instead.
    """
    if isinstance(day, bool) or not isinstance(day, int) or day < 0:
        raise ValueError('Calendar day targets must be nonnegative integers')
    midnight = anchor.replace(hour=0, minute=0, second=0, microsecond=0)
    return elapsed_target(midnight, timedelta(days=day))
