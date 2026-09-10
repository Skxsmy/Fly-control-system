import test from 'node:test';
import assert from 'node:assert/strict';
import {endAfterMove} from './reminder-window.ts';
test('moving an earlier date preserves duration without retaining the old end', () => {
  assert.equal(endAfterMove('2026-09-10T09:00','2026-09-11T09:00','2026-09-11T19:00'),'2026-09-10T19:00');
});
test('blank intermediate input does not lose the original window', () => {
  assert.equal(endAfterMove('','2026-09-11T09:00','2026-09-11T19:00'),'');
  assert.equal(endAfterMove('2026-09-12T09:00','2026-09-11T09:00','2026-09-11T19:00'),'2026-09-12T19:00');
});
test('lab-local duration remains exact across a browser DST boundary', () => {
  assert.equal(endAfterMove('2026-11-01T00:00','2026-09-11T09:00','2026-09-11T19:00'),'2026-11-01T10:00');
});
