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

test('a point reminder remains today work before and after its scheduled time', () => {
  const task = {due:'2026-09-25T10:00',end:'2026-09-25T10:00'};
  for (const time of ['00:00', '09:59', '10:00', '10:01', '23:59:59']) {
    assert.equal(isTodayWork(task,`2026-09-25T${time}`),true);
    assert.equal(isOverdue(task,`2026-09-25T${time}`),false);
  }
  assert.equal(isOverdue(task,'2026-09-26T00:00'),true);
  assert.equal(isTodayWork(task,'2026-09-26T00:00'),false);
});

test('a 30-minute embryo collection reminder does not become overdue at its instant', () => {
  const task = {due:'2026-09-25T23:55',end:'2026-09-25T23:55'};
  assert.equal(isTodayWork(task,'2026-09-25T23:56'),true);
  assert.equal(isOverdue(task,'2026-09-25T23:56'),false);
  assert.equal(isOverdue(task,'2026-09-26T00:00'),true);
});

test('all-day collection remains today work until midnight', () => {
  const task = {due:'2026-09-25T00:00',end:'2026-09-25T23:59',all_day:true};
  assert.equal(isTodayWork(task,'2026-09-25T23:59:59'),true);
  assert.equal(isOverdue(task,'2026-09-25T23:59:59'),false);
  assert.equal(isOverdue(task,'2026-09-26T00:00'),true);
});

test('ongoing stock renewal stays in today work and calendar from its start day', () => {
  const task = {due:'2026-09-25T00:00',end:'2026-09-25T00:00',status:'pending',all_day:true,open_ended:true};
  assert.equal(occursOnDay(task,'2026-09-24'),false);
  assert.equal(isTodayWork(task,'2026-09-24T23:59'),false);
  for (const day of ['2026-09-25', '2026-09-26', '2026-10-03', '2027-01-01']) {
    assert.equal(occursOnDay(task,day),true);
    assert.equal(isTodayWork(task,`${day}T18:00`),true);
    assert.equal(isOverdue(task,`${day}T18:00`),false);
  }
});

test('resolved ongoing reminders disappear from day work, calendar and attention', () => {
  for (const status of ['done', 'cancelled', 'skipped', 'disabled']) {
    const task = {due:'2026-09-25T00:00',end:'2026-09-25T00:00',status,open_ended:true};
    for (const day of ['2026-09-25', '2026-09-26']) {
      assert.equal(occursOnDay(task,day),false);
      assert.equal(isTodayWork(task,`${day}T18:00`),false);
      assert.equal(isOverdue(task,`${day}T18:00`),false);
    }
  }
});

test('resolved point and bounded reminders do not need attention', () => {
  const point = {due:'2026-09-25T09:00',end:'2026-09-25T09:00',status:'done'};
  const window = {...point,end:'2026-09-25T11:00'};
  for (const task of [point, window]) {
    assert.equal(occursOnDay(task,'2026-09-25'),false);
    assert.equal(isOverdue(task,'2026-09-25T15:00'),false);
    assert.equal(isTodayWork(task,'2026-09-25T15:00'),false);
    assert.equal(isOverdue(task,'2026-09-26T00:00'),false);
  }
});
