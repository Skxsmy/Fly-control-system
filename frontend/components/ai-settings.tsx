'use client';

import { useEffect, useId, useRef, useState, type SubmitEvent } from 'react';
import { Check, ChevronDown, CircleCheck, Download, Plug, Search, Server, Globe, Trash2 } from 'lucide-react';
import { Button } from './ui/button';
import { Field } from './fly-forms';
import { fmtDate, t } from '@/lib/i18n';
import { aiRequest, type AIModelsRequest, type AIModelsResponse, type AIProfileName, type AISettingsState, type AISettingsUpdate } from '@/lib/ai-types';

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
function submittedDraft(form: HTMLFormElement, draft: ProfileDraft): ProfileDraft {
  const values = new FormData(form);
  return {...draft, endpoint: textValue(values, 'endpoint').trim(), model: textValue(values, 'model').trim(), key: textValue(values, 'api_key')};
}

export function AISettings({onSaved}: {onSaved?: () => void}) {
  const [settings, setSettings] = useState<AISettingsState | null>(null);
  const [drafts, setDrafts] = useState<Drafts | null>(null);
  const [profile, setProfile] = useState<AIProfileName>('cloud');
  const [busy, setBusy] = useState<'save' | 'test' | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [models, setModels] = useState<AIModelsResponse | null>(null);
  const [modelsBusy, setModelsBusy] = useState(false);
  const [modelsError, setModelsError] = useState('');
  const [modelSearch, setModelSearch] = useState('');
  const [pickerOpen, setPickerOpen] = useState(false);
  const [reload, setReload] = useState(0);
  const request = useRef<AbortController | null>(null);
  const modelsRequest = useRef<AbortController | null>(null);
  const modelsGeneration = useRef(0);
  const modelInput = useRef<HTMLInputElement | null>(null);
  const statusId = useId();
  const modelsStatusId = useId();
  const modelsPickerId = useId();

  function invalidateModels() {
    modelsRequest.current?.abort(); modelsGeneration.current += 1;
    setModels(null); setModelsBusy(false); setModelsError(''); setModelSearch(''); setPickerOpen(false);
  }

  async function loadModels(name: AIProfileName, active: ProfileDraft, showPicker: boolean) {
    modelsRequest.current?.abort();
    const generation = ++modelsGeneration.current;
    const controller = new AbortController();
    modelsRequest.current = controller;
    setModels(null); setModelsBusy(true); setModelsError(''); setModelSearch(''); setPickerOpen(false);
    const payload: AIModelsRequest = {
      profile: name, endpoint: active.endpoint,
      ...(active.key ? {api_key: active.key} : active.removeKey ? {api_key: null} : {}),
    };
    try {
      const result = await aiRequest<AIModelsResponse>('/models', 'POST', payload, controller.signal);
      if (controller.signal.aborted || generation !== modelsGeneration.current) return;
      setModels(result); setPickerOpen(showPicker);
    } catch (reason) {
      if (!controller.signal.aborted && generation === modelsGeneration.current) setModelsError((reason as Error).message);
    } finally {
      if (!controller.signal.aborted && generation === modelsGeneration.current) setModelsBusy(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    request.current = controller;
    void aiRequest<AISettingsState>('/settings', 'GET', undefined, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      setSettings(value); setDrafts(draftsFrom(value)); setProfile(value.active_profile); setError('');
      const active = draftsFrom(value)[value.active_profile];
      if (active.endpoint && (active.model || value.profiles[value.active_profile].has_api_key)) void loadModels(value.active_profile, active, false);
    }).catch(reason => {if (!controller.signal.aborted) setError((reason as Error).message);});
    return () => {controller.abort(); request.current?.abort(); modelsRequest.current?.abort(); modelsGeneration.current += 1;};
  }, [reload]);

  function fetchModels(form: HTMLFormElement | null) {
    if (!form || !drafts || busy) return;
    if (!form.reportValidity()) return;
    const active = submittedDraft(form, drafts[profile]);
    setDrafts(current => current ? {...current, [profile]: active} : current);
    setNotice(''); setError('');
    void loadModels(profile, active, true);
  }

  function edit(values: Partial<ProfileDraft>) {
    if ('endpoint' in values || 'key' in values || 'removeKey' in values) invalidateModels();
    setDrafts(current => current ? {...current, [profile]: {...current[profile], ...values}} : current);
    setNotice(''); setError('');
  }

  function switchProfile(name: AIProfileName, form: HTMLFormElement | null) {
    invalidateModels();
    if (form) {
      const values = new FormData(form);
      setDrafts(current => current ? {...current, [profile]: {...current[profile], endpoint: textValue(values, 'endpoint'), model: textValue(values, 'model'), key: textValue(values, 'api_key')}} : current);
    }
    setProfile(name); setNotice(''); setError('');
    const next = drafts?.[name];
    if (next?.endpoint && (next.model || next.key || settings?.profiles[name].has_api_key)) void loadModels(name, next, false);
  }

  async function save(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!drafts || !settings || busy || modelsBusy) return;
    const submitter = event.nativeEvent.submitter as HTMLButtonElement | null;
    const test = submitter?.value === 'test';
    // Read the submitted inputs as well as state, including autofill and fast edits.
    const activeDraft = submittedDraft(event.currentTarget, drafts[profile]);
    if (test && !activeDraft.model) {setError(t('error.ai_model_required')); modelInput.current?.focus(); return;}
    const payload: AISettingsUpdate = {active_profile: profile, profiles: {
      [profile]: {
        endpoint: activeDraft.endpoint, model: activeDraft.model,
        ...(activeDraft.key ? {api_key: activeDraft.key} : activeDraft.removeKey ? {api_key: null} : {}),
      },
    }};
    const controller = new AbortController();
    invalidateModels();
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
  const status = !dirty && stored.test_status === 'connected' ? 'connected' : models ? 'reachable' : dirty ? 'untested' : stored.test_status;
  const visibleModels = models?.models.filter(model => model.id.toLocaleLowerCase().includes(modelSearch.toLocaleLowerCase())) ?? [];
  return <section className="panel ai-settings-panel" aria-labelledby="ai-connection-title">
    <div className="ai-section-heading"><h2 id="ai-connection-title"><Plug size={18}/>{t('ai.title')}</h2><span className={`pill ${status === 'connected' || status === 'reachable' ? 'green' : status === 'error' ? 'amber' : 'neutral'}`}>{t(status === 'connected' ? 'ai.connected' : status === 'reachable' ? 'ai.reachable' : status === 'error' ? 'ai.connectionError' : 'ai.untested')}</span></div>
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
        <div className="ai-key-field">
          <Field label={t(profile === 'local' ? 'ai.keyOptional' : 'ai.key')} hint={t('ai.keyStorage')}><input name="api_key" type="password" autoComplete="new-password" spellCheck={false} value={draft.key} onChange={event => edit({key: event.target.value, removeKey: false})} placeholder={t(stored.has_api_key && !draft.removeKey && !changedOrigin ? 'ai.keyReplace' : 'ai.keyNew')}/></Field>
          {stored.has_api_key && !changedOrigin && <div className="ai-key-status">
            <span>{draft.removeKey ? t('ai.keyClearPending') : <><Check size={15}/>{t(stored.api_key_source === 'environment' ? 'ai.keyEnvironment' : 'ai.keySaved')}</>}</span>
            {stored.api_key_source !== 'environment' && <Button type="button" variant="ghost" onClick={() => edit({removeKey: !draft.removeKey, key: ''})}>{!draft.removeKey && <Trash2 size={14}/>} {t(draft.removeKey ? 'ai.keyUndo' : 'ai.keyClear')}</Button>}
          </div>}
          {changedOrigin && stored.has_api_key && !draft.key && <p className="notice warning">{t('ai.originChanged')}</p>}
        </div>
        <div className="ai-model-field">
          <Field label={t('ai.model')} hint={t('ai.modelHint')}><input ref={modelInput} name="model" autoComplete="off" spellCheck={false} value={draft.model} onChange={event => edit({model: event.target.value})} placeholder={t('ai.modelPlaceholder')}/></Field>
          <div className="ai-model-actions">
            <Button type="button" variant="outline" disabled={modelsBusy || !draft.endpoint.trim()} onClick={event => fetchModels(event.currentTarget.form)} aria-describedby={modelsStatusId}>{modelsBusy ? <><span className="spinner"/>{t('ai.fetchingModels')}</> : <><Download size={15}/>{t('ai.fetchModels')}</>}</Button>
            {modelsBusy && <Button type="button" variant="ghost" onClick={invalidateModels}>{t('ai.cancelFetch')}</Button>}
            {models && <Button type="button" variant="outline" aria-expanded={pickerOpen} aria-controls={modelsPickerId} onClick={() => setPickerOpen(open => !open)}>{t('ai.chooseModel')}<ChevronDown size={15}/></Button>}
          </div>
          <div id={modelsStatusId} className="ai-model-status" aria-live="polite">
            {modelsError && <p className="error" role="alert">{modelsError}</p>}
            {models && <p className="ai-success"><CircleCheck size={16}/>{t(models.models.length === 1 ? 'ai.modelsFound.one' : 'ai.modelsFound', {count: models.models.length})}</p>}
          </div>
          {models && pickerOpen && <div id={modelsPickerId} className="ai-model-picker">
            <div className="ai-model-search"><Search size={16}/><input type="search" aria-label={t('ai.modelSearch')} value={modelSearch} onChange={event => setModelSearch(event.target.value)} onKeyDown={event => {if (event.key === 'Enter') event.preventDefault();}} placeholder={t('ai.modelSearchPlaceholder')}/></div>
            <ul className="ai-model-list" aria-label={t('ai.availableModels')}>
              {visibleModels.map(model => <li key={model.id}><button type="button" className={draft.model === model.id ? 'selected' : ''} onClick={() => {edit({model: model.id}); setPickerOpen(false); modelInput.current?.focus();}}><span>{model.id}</span>{draft.model === model.id && <Check size={15}/>}</button></li>)}
              {!visibleModels.length && <li className="ai-model-empty">{t('ai.modelsNoMatch')}</li>}
            </ul>
            {models.truncated && <p className="ai-help">{t('ai.modelsTruncated', {count: models.models.length})}</p>}
          </div>}
        </div>
      </fieldset>
      {profile === 'local' && <p className="ai-help">{t('ai.localHint')}</p>}
      <div id={statusId} className="ai-save-status" aria-live="polite">
        {error && <p className="error" role="alert">{error}</p>}
        {notice && <p className="ai-success"><CircleCheck size={16}/>{notice}</p>}
        {!dirty && stored.tested_at && <p className="ai-help">{t('ai.testedAt', {at: fmtDate(stored.tested_at, {dateStyle: 'medium', timeStyle: 'short'})})}</p>}
      </div>
      <footer className="form-footer ai-settings-actions">
        <p className="ai-help">{t('ai.generationTestHint')}</p>
        <Button type="submit" value="save" variant="outline" disabled={!!busy || modelsBusy}>{busy === 'save' ? <><span className="spinner"/>{t('ai.saving')}</> : t('ai.save')}</Button>
        <Button type="submit" value="test" disabled={!!busy || modelsBusy}>{busy === 'test' ? <><span className="spinner"/>{t('ai.testing')}</> : <><Plug size={16}/>{t('ai.saveTest')}</>}</Button>
      </footer>
    </form>
  </section>;
}
