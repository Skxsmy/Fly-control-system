'use client';

import { useEffect, useId, useRef, useState, type SubmitEvent } from 'react';
import { Check, CircleCheck, Plug, Server, Globe, Trash2 } from 'lucide-react';
import { Button } from './ui/button';
import { Field } from './fly-forms';
import { fmtDate, t } from '@/lib/i18n';
import { aiRequest, type AIProfileName, type AISettingsState, type AISettingsUpdate } from '@/lib/ai-types';

type ProfileDraft = {endpoint: string; model: string; key: string; removeKey: boolean};
type Drafts = Record<AIProfileName, ProfileDraft>;

function draftsFrom(value: AISettingsState): Drafts {
  return Object.fromEntries((['cloud', 'local'] as const).map(name => [name, {
    endpoint: value.profiles[name].endpoint,
    model: value.profiles[name].model,
    key: '',
    removeKey: false,
  }])) as Drafts;
}

function origin(value: string) {try {return new URL(value).origin;} catch {return '';}}
function textValue(form: FormData, name: string) {const value = form.get(name); return typeof value === 'string' ? value : '';}

export function AISettings({onSaved}: {onSaved?: () => void}) {
  const [settings, setSettings] = useState<AISettingsState | null>(null);
  const [drafts, setDrafts] = useState<Drafts | null>(null);
  const [profile, setProfile] = useState<AIProfileName>('cloud');
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | null>(null);
  const statusId = useId();

  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    void aiRequest<AISettingsState>('/settings', 'GET', undefined, controller.signal).then(value => {
      setSettings(value); setDrafts(draftsFrom(value)); setProfile(value.active_profile); setError('');
    }).catch(reason => {if (!controller.signal.aborted) setError((reason as Error).message);});
    return () => {controller.abort(); request.current?.abort();};
  }, [reload]);

  function edit(values: Partial<ProfileDraft>) {
    setDrafts(current => current ? {...current, [profile]: {...current[profile], ...values}} : current);
    setNotice(''); setError('');
  }

  function switchProfile(name: AIProfileName, form: HTMLFormElement | null) {
    if (form) {
      const values = new FormData(form);
      setDrafts(current => current ? {...current, [profile]: {...current[profile], endpoint: textValue(values, 'endpoint'), model: textValue(values, 'model'), key: textValue(values, 'api_key')}} : current);
    }
    setProfile(name); setNotice(''); setError('');
  }

  async function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!drafts || !settings || busy) return;
    const submitter = event.nativeEvent.submitter as HTMLButtonElement | null;
    const test = submitter?.value === 'test';
    const formData = new FormData(event.currentTarget);
    // Read the submitted inputs as well as state, including autofill and fast edits.
    const activeDraft: ProfileDraft = {
      ...drafts[profile],
      endpoint: textValue(formData, 'endpoint').trim(),
      model: textValue(formData, 'model').trim(),
      key: textValue(formData, 'api_key'),
    };
    const payload: AISettingsUpdate = {active_profile: profile, profiles: {
      [profile]: {
        endpoint: activeDraft.endpoint, model: activeDraft.model,
        ...(activeDraft.key ? {api_key: activeDraft.key} : activeDraft.removeKey ? {api_key: null} : {}),
      },
    }};
    const controller = new AbortController();
    request.current = controller;
    setBusy(test ? 'test' : 'save'); setError(''); setNotice('');
    try {
      const saved = await aiRequest<AISettingsState>('/settings', 'PUT', payload, controller.signal);
      setSettings(saved);
      setDrafts(current => current ? {...current, [profile]: draftsFrom(saved)[profile]} : draftsFrom(saved));
      setProfile(saved.active_profile);
      setNotice(t('ai.saved')); onSaved?.();
      if (test) {
        const result = await aiRequest<{status: 'connected'; profile: AIProfileName; model: string; tested_at: string}>('/test', 'POST', {expected_connection_revision: saved.connection_revision}, controller.signal);
        setSettings(current => current ? {...current, profiles: {...current.profiles, [result.profile]: {...current.profiles[result.profile], tested_at: result.tested_at, test_status: 'connected'}}} : current);
        setNotice(t('ai.connected'));
      }
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError((reason as Error).message);
        if (test) setSettings(current => current ? {...current, profiles: {...current.profiles, [profile]: {...current.profiles[profile], test_status: 'error'}}} : current);
      }
    } finally {if (!controller.signal.aborted) setBusy(null);}
  }

  if (!settings || !drafts) return <section className="panel ai-settings-panel">
    <h2>{t('ai.title')}</h2>
    {error ? <><p className="error" role="alert">{error}</p><Button variant="outline" onClick={() => {setError(''); setReload(x => x + 1);}}>{t('common.retry')}</Button></> : <p className="ai-loading"><span className="spinner"/>{t('common.loading')}</p>}
  </section>;

  const draft = drafts[profile];
  const stored = settings.profiles[profile];
  const changedOrigin = !!stored.endpoint && !!origin(draft.endpoint) && origin(draft.endpoint) !== origin(stored.endpoint);
  const dirty = profile !== settings.active_profile || draft.endpoint !== stored.endpoint || draft.model !== stored.model || !!draft.key || draft.removeKey;
  const status = dirty ? 'untested' : stored.test_status;
  return <section className="panel ai-settings-panel" aria-labelledby="ai-connection-title">
    <div className="ai-section-heading"><h2 id="ai-connection-title"><Plug size={18}/>{t('ai.title')}</h2><span className={`pill ${status === 'connected' ? 'green' : status === 'error' ? 'amber' : 'neutral'}`}>{t(status === 'connected' ? 'ai.connected' : status === 'error' ? 'ai.connectionError' : 'ai.untested')}</span></div>
    <form className="fly-form" onSubmit={save} aria-busy={!!busy} aria-describedby={statusId}>
      <fieldset className="ai-profile-options" disabled={!!busy}>
        <legend>{t('ai.profile')}</legend>
        {(['cloud', 'local'] as const).map(name => <label className={profile === name ? 'selected' : ''} key={name}>
          <input type="radio" name="ai_profile" value={name} checked={profile === name} onChange={event => switchProfile(name, event.currentTarget.form)}/>
          {name === 'cloud' ? <Globe size={17}/> : <Server size={17}/>}{t(`ai.${name}`)}
        </label>)}
      </fieldset>
      <fieldset className="ai-settings-fields" disabled={!!busy}>
        <Field label={t('ai.endpoint')} hint={t('ai.endpointHint')}><input name="endpoint" type="url" required autoComplete="off" spellCheck={false} value={draft.endpoint} onChange={event => edit({endpoint: event.target.value})} placeholder={t(`ai.${profile}EndpointPlaceholder`)}/></Field>
        <Field label={t('ai.model')}><input name="model" required autoComplete="off" spellCheck={false} value={draft.model} onChange={event => edit({model: event.target.value})} placeholder={t('ai.modelPlaceholder')}/></Field>
        <div className="ai-key-field">
          <Field label={t(profile === 'local' ? 'ai.keyOptional' : 'ai.key')} hint={t('ai.keyStorage')}><input name="api_key" type="password" autoComplete="new-password" spellCheck={false} value={draft.key} onChange={event => edit({key: event.target.value, removeKey: false})} placeholder={t(stored.has_api_key && !draft.removeKey && !changedOrigin ? 'ai.keyReplace' : 'ai.keyNew')}/></Field>
          {stored.has_api_key && !changedOrigin && <div className="ai-key-status">
            <span>{draft.removeKey ? t('ai.keyClearPending') : <><Check size={15}/>{t(stored.api_key_source === 'environment' ? 'ai.keyEnvironment' : 'ai.keySaved')}</>}</span>
            {stored.api_key_source !== 'environment' && <Button type="button" variant="ghost" onClick={() => edit({removeKey: !draft.removeKey, key: ''})}>{!draft.removeKey && <Trash2 size={14}/>} {t(draft.removeKey ? 'ai.keyUndo' : 'ai.keyClear')}</Button>}
          </div>}
          {changedOrigin && stored.has_api_key && !draft.key && <p className="notice warning">{t('ai.originChanged')}</p>}
        </div>
      </fieldset>
      {profile === 'local' && <p className="ai-help">{t('ai.localHint')}</p>}
      <div id={statusId} className="ai-save-status" aria-live="polite">
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className="ai-success"><CircleCheck size={16}/>{notice}</p>}
        {!dirty && stored.tested_at && <p className="ai-help">{t('ai.testedAt', {at: fmtDate(stored.tested_at, {dateStyle: 'medium', timeStyle: 'short'})})}</p>}
      </div>
      <footer className="form-footer ai-settings-actions">
        <Button type="submit" value="save" variant="outline" disabled={!!busy}>{busy === 'save' ? <><span className="spinner"/>{t('ai.saving')}</> : t('ai.save')}</Button>
        <Button type="submit" value="test" disabled={!!busy}>{busy === 'test' ? <><span className="spinner"/>{t('ai.testing')}</> : <><Plug size={16}/>{t('ai.saveTest')}</>}</Button>
      </footer>
    </form>
  </section>;
}
