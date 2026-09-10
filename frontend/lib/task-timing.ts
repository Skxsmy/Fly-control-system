type TimedTask = {due: string; end: string};

export const isOverdue = (task: TimedTask, now: string) => task.end < now;
export const occursOnDay = (task: TimedTask, day: string) => task.due.slice(0, 10) <= day && task.end.slice(0, 10) >= day;
export const isTodayWork = (task: TimedTask, now: string) => occursOnDay(task, now.slice(0, 10)) && !isOverdue(task, now);
