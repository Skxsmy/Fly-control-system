type TimedTask = {due: string; end: string; status?: string; all_day?: boolean; open_ended?: boolean};

const isPending = (task: TimedTask) => task.status === undefined || task.status === 'pending';

export const isOverdue = (task: TimedTask, now: string) => {
  if (!isPending(task) || task.open_ended) return false;
  // A scheduled instant is a reminder, not a zero-length completion window.
  if (task.due === task.end || task.all_day) return task.end.slice(0, 10) < now.slice(0, 10);
  return task.end < now;
};
export const occursOnDay = (task: TimedTask, day: string) => isPending(task) && task.due.slice(0, 10) <= day && (task.open_ended || task.end.slice(0, 10) >= day);
export const isTodayWork = (task: TimedTask, now: string) => occursOnDay(task, now.slice(0, 10)) && !isOverdue(task, now);
