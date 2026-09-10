import en from './en';

export type Messages = Record<string, string>;
const locales: Record<string, Messages> = { en };
const localeNames: Record<string, string> = {en: 'English'};
let currentLocale = 'en';

/** Register complete or partial language packs. Missing keys fall back to English. */
export function registerLocale(locale: string, messages: Messages, displayName = locale) { locales[locale] = messages; localeNames[locale] = displayName; }
export function availableLocales() {return Object.keys(locales).map(code => ({code, name: localeNames[code]}));}
export function setLocale(locale: string) {
  currentLocale = locales[locale] ? locale : 'en';
  if (typeof document !== 'undefined') document.documentElement.lang = currentLocale;
}
export function t(key: string, values: Record<string, string | number> = {}) {
  const message = locales[currentLocale]?.[key] ?? en[key] ?? key;
  return message.replace(/\{(\w+)\}/g, (_, name: string) => String(values[name] ?? `{${name}}`));
}
export function fmtDate(value: string, options: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }) {
  return new Intl.DateTimeFormat(currentLocale, options).format(new Date(value.length === 10 ? `${value}T12:00:00` : value));
}
export function fmtNumber(value: number) { return new Intl.NumberFormat(currentLocale, {maximumFractionDigits: 1}).format(value); }
export function fmtTime(value: string) { return new Intl.DateTimeFormat(currentLocale, {hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date(value)); }
export function weekday(index: number) { return fmtDate(`2026-09-${String(7 + index).padStart(2, '0')}`, {weekday: 'long'}); }
