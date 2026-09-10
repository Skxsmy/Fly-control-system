// Lab-local arithmetic: append UTC only to avoid browser-zone/DST conversion.
export function endAfterMove(start: string, originalStart: string, originalEnd: string): string {
  const at = Date.parse(start + 'Z');
  const duration = Date.parse(originalEnd + 'Z') - Date.parse(originalStart + 'Z');
  if (!Number.isFinite(at) || !Number.isFinite(duration) || duration < 0) return '';
  return new Date(at + duration).toISOString().slice(0, 16);
}
