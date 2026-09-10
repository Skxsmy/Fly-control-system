import test from 'node:test';
import assert from 'node:assert/strict';
import {isOverdue, occursOnDay, isTodayWork} from './task-timing.ts';

test('a missed morning window needs attention that afternoon', () => {
  const task = {due:'2026-09-25T09:00',end:'2026-09-25T11:00'};
  assert.equal(isTodayWork(task,'2026-09-25T09:00'),true);
  assert.equal(isOverdue(task,'2026-09-25T11:00'),false);
  assert.equal(isOverdue(task,'2026-09-25T15:00'),true);
  assert.equal(isTodayWork(task,'2026-09-25T15:00'),false);
});
test('an unfinished window stays overdue across midnight', () => {
  const task = {due:'2026-09-25T19:00',end:'2026-09-25T21:00'};
  assert.equal(isOverdue(task,'2026-09-26T00:00'),true);
  assert.equal(isTodayWork(task,'2026-09-26T00:00'),false);
});
test('a multi-day custom task appears throughout its available interval', () => {
  const task = {due:'2026-09-25T23:00',end:'2026-09-28T12:00'};
  assert.equal(occursOnDay(task,'2026-09-24'),false);
  assert.equal(occursOnDay(task,'2026-09-26'),true);
  assert.equal(isTodayWork(task,'2026-09-28T09:00'),true);
  assert.equal(isTodayWork(task,'2026-09-28T13:00'),false);
});
