import test from 'node:test';
import assert from 'node:assert/strict';
import {collectionClockAt} from './collection-guidance.ts';

const makeCulture = (values = {}) => ({
  initial_temperature: 25,
  template: {virgin_hours25: 8, virgin_hours18: 16},
  logs: [{action: 'clear', at: '2026-09-20T21:00'}],
  temperatures: [],
  ...values,
});

test('time advancing beyond the selected 25°C interval expires the clock', () => {
  const culture = makeCulture();
  assert.equal(collectionClockAt(culture, '2026-09-21T04:59').state, 'within');
  assert.equal(collectionClockAt(culture, '2026-09-21T05:00').state, 'elapsed');
  assert.equal(collectionClockAt(culture, '2026-09-21T09:00').state, 'elapsed');
  assert.equal(collectionClockAt(culture, '2026-09-21T09:00').deadline, '2026-09-21T05:00');
});

test('a backdated collection ignores future clears and future temperature changes', () => {
  const culture = makeCulture({
    logs: [{action: 'clear', at: '2026-09-21T10:00'}, {action: 'clear', at: '2026-09-20T21:00'}],
    temperatures: [{at: '2026-09-21T09:30', temperature: 18}],
  });
  const atNine = collectionClockAt(culture, '2026-09-21T09:00');
  assert.equal(atNine.state, 'elapsed');
  assert.equal(atNine.last_clear, '2026-09-20T21:00');
  assert.equal(atNine.temperature, 25);
  assert.equal(collectionClockAt(culture, '2026-09-20T20:00').state, 'unknown');
});

test('collecting alone never resets the complete-clear clock', () => {
  const culture = makeCulture({logs: [{action: 'clear', at: '2026-09-20T21:00'}, {action: 'collect', at: '2026-09-21T04:00'}]});
  assert.equal(collectionClockAt(culture, '2026-09-21T09:00').deadline, '2026-09-21T05:00');
  assert.equal(collectionClockAt(makeCulture({logs: [{action: 'collect', at: '2026-09-21T04:00'}]}), '2026-09-21T09:00').state, 'unknown');
});

test('any temperature change after clearing requires review, even if it later returns to 25°C', () => {
  const culture = makeCulture({temperatures: [{at: '2026-09-21T03:00', temperature: 25}, {at: '2026-09-21T01:00', temperature: 18}]});
  const clock = collectionClockAt(culture, '2026-09-21T04:00');
  assert.equal(clock.state, 'mixed');
  assert.equal(clock.deadline, null);
  assert.equal(clock.temperature, 25);
});

test('a new complete clear starts a fresh interval at the temperature recorded at that time', () => {
  const culture = makeCulture({initial_temperature: 25, temperatures: [{at: '2026-09-20T21:00', temperature: 18}]});
  assert.equal(collectionClockAt(culture, '2026-09-21T09:00').state, 'within');
  assert.equal(collectionClockAt(culture, '2026-09-21T09:00').deadline, '2026-09-21T13:00');
  assert.equal(collectionClockAt(culture, '2026-09-21T13:00').state, 'elapsed');
});
