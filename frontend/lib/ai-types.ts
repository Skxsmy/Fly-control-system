import { t } from './i18n';

export type AIProfileName = 'cloud' | 'local';
export type AIProfile = {
  endpoint: string;
  model: string;
  has_api_key: boolean;
  api_key_source?: 'saved' | 'environment' | 'none';
  tested_at: string | null;
  test_status: 'untested' | 'connected' | 'error';
};
export type AISettingsState = {
  connection_revision: string;
  active_profile: AIProfileName;
  profiles: Record<AIProfileName, AIProfile>;
};
export type AISettingsUpdate = {
  active_profile: AIProfileName;
  profiles: Partial<Record<AIProfileName, {endpoint: string; model: string; api_key?: string | null}>>;
};
export type AIHistoryMessage = {role: 'user' | 'assistant'; content: string};
export type AIContext = {
  included: boolean;
  scope: 'none' | 'all' | 'selected';
  counts: Record<'containers' | 'temperatures' | 'logs' | 'events' | 'egg_batches' | 'availability' | 'plans', number>;
  truncated: boolean;
};
export type AIChatResponse = {
  reply: string;
  profile: AIProfileName;
  model: string;
  created_at: string;
  context: AIContext;
};
export type AIChatMessage = AIHistoryMessage & {id: string; context?: AIContext; model?: string};

export class AIRequestError extends Error {
  constructor(public code: string, message: string) {super(message); this.name = 'AIRequestError';}
}

/** Requests are kept separate from the general client so chat can be cancelled. */
export async function aiRequest<T>(path: string, method = 'GET', body?: unknown, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/ai${path}`, {
      method,
      ...(body === undefined ? {} : {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new Error(t('error.connection'));
  }
  if (!response.ok) {
    const value = await response.json().catch(() => ({})) as {detail?: unknown};
    const key = typeof value.detail === 'string' ? `error.${value.detail}` : 'error.validation';
    throw new AIRequestError(typeof value.detail === 'string' ? value.detail : 'validation', t(key) === key ? t('error.generic') : t(key));
  }
  try {return await response.json() as T;}
  catch {throw new Error(t('error.ai_invalid_response'));}
}
