import type {Culture} from './types';

type CollectionCulture = Pick<Culture, 'logs' | 'temperatures' | 'initial_temperature' | 'template'>;
export type CollectionClock = {
  state: 'unknown' | 'within' | 'elapsed' | 'mixed';
  last_clear: string | null;
  deadline: string | null;
  temperature: number;
  protocolHours: number;
};

// The API uses lab-local timestamps. Avoid the browser's timezone and DST rules.
function localTime(value: string): number {
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/.test(value) ? Date.parse(value + 'Z') : NaN;
}

/** Reconstruct the clock at the actual manipulation time, including backdated entries. */
export function collectionClockAt(culture: CollectionCulture, at: string): CollectionClock {
  const evaluatedAt = localTime(at);
  const temperatures = culture.temperatures
    .filter(item => localTime(item.at) <= evaluatedAt)
    .sort((a, b) => localTime(a.at) - localTime(b.at));
  const currentTemperature = temperatures.at(-1)?.temperature ?? culture.initial_temperature;
  const hoursAt = (temperature: number) => culture.template[temperature === 18 ? 'virgin_hours18' : 'virgin_hours25'];
  const unknown: CollectionClock = {state: 'unknown', last_clear: null, deadline: null, temperature: currentTemperature, protocolHours: hoursAt(currentTemperature)};
  if (!Number.isFinite(evaluatedAt)) return unknown;
  const clears = culture.logs.filter(item => item.action === 'clear' && localTime(item.at) <= evaluatedAt);
  const last = clears.sort((a, b) => localTime(a.at) - localTime(b.at)).at(-1);
  if (!last) return unknown;
  const clearedAt = localTime(last.at);
  const temperature = temperatures.filter(item => localTime(item.at) <= clearedAt).at(-1)?.temperature ?? culture.initial_temperature;
  const protocolHours = hoursAt(temperature);
  const changed = temperatures.some(item => localTime(item.at) > clearedAt && item.temperature !== temperature);
  if (changed) return {state: 'mixed', last_clear: last.at, deadline: null, temperature: currentTemperature, protocolHours: hoursAt(currentTemperature)};
  const deadline = clearedAt + protocolHours * 60 * 60 * 1000;
  return {
    state: evaluatedAt >= deadline ? 'elapsed' : 'within', last_clear: last.at,
    deadline: new Date(deadline).toISOString().slice(0, 16), temperature, protocolHours,
  };
}
