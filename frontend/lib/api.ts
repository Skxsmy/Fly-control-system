import { t } from './i18n';

export async function api<T = unknown>(path: string, method = 'GET', body?: unknown): Promise<T> {
  let response: Response;
  const options: RequestInit = {method};
  if (body !== undefined) {
    if (method === 'GET' || method === 'HEAD') throw new Error(t('error.generic'));
    options.headers = {'Content-Type': 'application/json'};
    options.body = JSON.stringify(body);
  }
  try { response = await fetch(`/api${path}`, options); }
  catch { throw new Error(t('error.connection')); }
  if (!response.ok) {
    const value = await response.json().catch(() => ({})) as {detail?: unknown};
    const key = typeof value.detail === 'string' ? `error.${value.detail}` : 'error.validation';
    throw new Error(t(key) === key ? t('error.generic') : t(key));
  }
  return response.json();
}
