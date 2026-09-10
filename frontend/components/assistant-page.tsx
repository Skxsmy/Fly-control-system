'use client';

import { useEffect, useId, useRef, useState, type MouseEvent, type SubmitEvent } from 'react';
import { ArrowUp, CalendarDays, FlaskConical, MessageSquare, Plus, Search, Settings2, Square } from 'lucide-react';
import { Button } from './ui/button';
import { Field } from './fly-forms';
import { fmtNumber, t } from '@/lib/i18n';
import { AIRequestError, aiRequest, type AIChatMessage, type AIChatResponse, type AIContext, type AISettingsState } from '@/lib/ai-types';
import type { AppState, Culture } from '@/lib/types';

type Session = {
  connection: string;
  messages: AIChatMessage[];
  draft: string;
  includeWorkspace: boolean;
  scope: 'all' | 'selected';
  selectedIds: string[];
  targetDate: string;
};
const emptySession = (): Session => ({connection: '', messages: [], draft: '', includeWorkspace: true, scope: 'all', selectedIds: [], targetDate: ''});
let session = emptySession();

export function resetAssistantSession() {session = emptySession();}

function cultureText(culture: Culture) {
  const genotype = culture.purpose === 'cross' ? `${culture.female_genotype} ♀ × ${culture.male_genotype} ♂` : culture.genotype;
  return `${culture.label || culture.id} · ${genotype || t(`kind.${culture.kind}`)}`;
}

function recentHistory(messages: AIChatMessage[]) {
  const result: AIChatMessage[] = [];
  let length = 0;
  for (let index = messages.length - 2; index >= 0 && result.length < 12; index -= 2) {
    const pair = messages.slice(index, index + 2);
    const size = pair.reduce((total, message) => total + message.content.length, 0);
    if (length + size > 72000) break;
    result.unshift(...pair); length += size;
  }
  return result;
}

function ContextUsed({context}: {context: AIContext}) {
  if (!context.included) return null;
  const keys = ['containers', 'events', 'egg_batches', 'logs', 'temperatures', 'availability', 'plans'] as const;
  return <div className="ai-context-used">
    <span>{t('ai.contextUsed')}: {keys.filter(key => context.counts[key] > 0).map(key => t(`ai.context.${key}${context.counts[key] === 1 ? '.one' : ''}`, {count: fmtNumber(context.counts[key])})).join(' · ') || t('common.none')}</span>
    {context.truncated && <span className="warning-text">{t('ai.contextTruncated')}</span>}
  </div>;
}

export function AssistantPage({state, initialContainerId, openSettings}: {state: AppState; initialContainerId?: string | null; openSettings: () => void}) {
  const changedInitialScope = !!initialContainerId && (session.scope !== 'selected' || session.selectedIds.length !== 1 || session.selectedIds[0] !== initialContainerId || !session.includeWorkspace);
  const [settings, setSettings] = useState<AISettingsState | null>(null);
  const [loadError, setLoadError] = useState('');
  const [reload, setReload] = useState(0);
  const [messages, setMessages] = useState<AIChatMessage[]>(changedInitialScope ? [] : session.messages);
  const [draft, setDraft] = useState(session.draft);
  const [includeWorkspace, setIncludeWorkspace] = useState(initialContainerId ? true : session.includeWorkspace);
  const [scope, setScope] = useState<'all' | 'selected'>(initialContainerId ? 'selected' : session.scope);
  const [selectedIds, setSelectedIds] = useState<string[]>(initialContainerId ? [initialContainerId] : session.selectedIds);
  const [targetDate, setTargetDate] = useState(session.targetDate);
  const [search, setSearch] = useState('');
  const [pending, setPending] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState(changedInitialScope && session.messages.length ? t('ai.scopeReset') : '');
  const request = useRef<AbortController | null>(null);
  const textInput = useRef<HTMLTextAreaElement | null>(null);
  const end = useRef<HTMLDivElement | null>(null);
  const instance = useId();
  const includeId = `${instance}-workspace`;
  const statusId = `${instance}-status`;
  const messageId = `${instance}-message`;
  const composerId = `${instance}-composer`;

  useEffect(() => {
    const controller = new AbortController();
    void aiRequest<AISettingsState>('/settings', 'GET', undefined, controller.signal).then(value => {
      const profile = value.profiles[value.active_profile];
      const connection = `${value.connection_revision}:${value.active_profile}:${profile.endpoint}:${profile.model}`;
      if (session.connection && session.connection !== connection) {
        if (session.messages.length) setNotice(t('ai.connectionReset'));
        session.messages = []; setMessages([]);
      }
      session.connection = connection;
      setSettings(value); setLoadError('');
    }).catch(reason => {if (!controller.signal.aborted) setLoadError((reason as Error).message);});
    return () => {controller.abort(); request.current?.abort();};
  }, [reload]);

  useEffect(() => {
    session = {...session, messages, draft, includeWorkspace, scope, selectedIds, targetDate};
  }, [messages, draft, includeWorkspace, scope, selectedIds, targetDate]);

  useEffect(() => {if (messages.length || pending) end.current?.scrollIntoView({block: 'nearest', behavior: 'smooth'});}, [messages.length, pending]);

  const active = settings?.profiles[settings.active_profile];
  const configured = !!active?.endpoint.trim() && !!active?.model.trim();
  const busy = !!pending;
  const existingIds = new Set(state.containers.map(container => container.id));
  const missingSelection = selectedIds.some(id => !existingIds.has(id));
  const invalidSelection = includeWorkspace && scope === 'selected' && (!selectedIds.length || missingSelection);
  const visibleContainers = state.containers.filter(container => `${container.id} ${cultureText(container)}`.toLowerCase().includes(search.toLowerCase()));
  const history = recentHistory(messages);
  const targetPrefix = targetDate ? t('ai.targetPrefix', {date: targetDate}) : '';

  function changeScope(update: {include?: boolean; scope?: 'all' | 'selected'; ids?: string[]}) {
    if (messages.length) setNotice(t('ai.scopeReset')); else setNotice('');
    setMessages([]); setError('');
    if (update.include !== undefined) setIncludeWorkspace(update.include);
    if (update.scope) setScope(update.scope);
    if (update.ids) setSelectedIds(update.ids);
  }

  function prefill(goal: 'l1' | 'l3') {
    const names = includeWorkspace && scope === 'selected' ? state.containers.filter(container => selectedIds.includes(container.id)).map(container => `${container.label} (${container.id})`).join(', ') : '';
    setDraft(t(`ai.prompt.${goal}`, {source: names ? t('ai.promptSource', {sources: names}) : ''}));
    setError(''); textInput.current?.focus();
  }

  function newConversation() {
    setMessages([]); setError(''); setNotice('');
    textInput.current?.focus();
  }

  async function send(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const formData = new FormData(event.currentTarget);
    const messageValue = formData.get('message');
    const input = typeof messageValue === 'string' ? messageValue.trim() : '';
    if (!input || busy || !configured || invalidSelection) return;
    const dateValue = formData.get('target_date');
    const submittedDate = typeof dateValue === 'string' ? dateValue : '';
    const submittedPrefix = submittedDate ? t('ai.targetPrefix', {date: submittedDate}) : '';
    const outbound = submittedPrefix + input;
    if (outbound.length > 8000) {setError(t('ai.messageTooLong', {count: 8000 - submittedPrefix.length})); return;}
    setTargetDate(submittedDate);
    const controller = new AbortController();
    request.current = controller;
    setDraft(input); setPending(outbound); setError(''); setNotice('');
    try {
      const response = await aiRequest<AIChatResponse>('/chat', 'POST', {
        message: outbound,
        history: history.map(({role, content}) => ({role, content})),
        include_workspace: includeWorkspace,
        expected_connection_revision: settings?.connection_revision,
        ...(includeWorkspace && scope === 'selected' ? {selected_container_ids: selectedIds} : {}),
      }, controller.signal);
      if (controller.signal.aborted) return;
      if (typeof response.reply !== 'string' || !response.reply.trim()) throw new Error(t('error.ai_empty_response'));
      const key = `${response.created_at}-${messages.length}`;
      setMessages(current => [...current, {id: `${key}-user`, role: 'user', content: outbound}, {id: `${key}-assistant`, role: 'assistant', content: response.reply, context: response.context, model: response.model}].slice(-100) as AIChatMessage[]);
      setDraft('');
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError((reason as Error).message);
        if (reason instanceof AIRequestError && reason.code === 'ai_connection_changed') {
          setMessages([]); setSettings(null); setReload(value => value + 1);
        }
      }
    } finally {
      if (request.current === controller) {setPending(''); request.current = null;}
    }
  }

  function cancel(event: MouseEvent<HTMLButtonElement>) {
    // Cancelling changes the footer controls during this click. Prevent the
    // default action from being interpreted as submission after that change.
    event.preventDefault();
    request.current?.abort(); request.current = null;
    setPending(''); setNotice(t('ai.cancelled')); textInput.current?.focus();
  }

  return <div className="assistant-layout">
    <section className="panel assistant-conversation" aria-label={t('ai.conversation')}>
      <header className="assistant-toolbar">
        <div className="assistant-model"><MessageSquare size={18}/><span>{active?.model || t('ai.notConnected')}</span>{active?.model && settings && <span className="pill neutral">{t(`ai.${settings.active_profile}`)}</span>}</div>
        <div><Button variant="ghost" disabled={busy || !messages.length} onClick={newConversation}><Plus size={16}/>{t('ai.newConversation')}</Button><Button variant="outline" disabled={busy} onClick={openSettings}><Settings2 size={16}/>{t('ai.connection')}</Button></div>
      </header>
      <div className="assistant-thread" role="log" aria-label={t('ai.conversation')} aria-live="polite" aria-relevant="additions">
        {loadError ? <div className="assistant-empty"><p className="error" role="alert">{loadError}</p><Button variant="outline" onClick={() => {setLoadError(''); setReload(value => value + 1);}}>{t('common.retry')}</Button></div> : !settings ? <div className="assistant-empty"><span className="spinner"/>{t('common.loading')}</div> : !configured ? <div className="assistant-empty"><span className="assistant-empty-icon"><MessageSquare size={27}/></span><h2>{t('ai.notConnected')}</h2><p>{t('ai.setupPrompt')}</p><Button onClick={openSettings}><Settings2 size={16}/>{t('ai.connect')}</Button></div> : !messages.length && !pending && <div className="assistant-empty"><span className="assistant-empty-icon"><FlaskConical size={27}/></span><h2>{t('ai.emptyTitle')}</h2></div>}
        {configured && messages.map(message => <article className={`assistant-message ${message.role}`} key={message.id}>
          <div className="assistant-message-label"><strong>{t(message.role === 'user' ? 'ai.you' : 'ai.suggestion')}</strong>{message.model && <span>{message.model}</span>}</div>
          <div className="assistant-message-content">{message.content}</div>
          {message.context && <ContextUsed context={message.context}/>}
        </article>)}
        {pending && <><article className="assistant-message user"><div className="assistant-message-label"><strong>{t('ai.you')}</strong></div><div className="assistant-message-content">{pending}</div></article><output className="assistant-waiting"><span className="spinner"/>{t('ai.sending')}</output></>}
        <div ref={end}/>
      </div>
      <form id={composerId} className="assistant-composer" onSubmit={send} aria-busy={busy} aria-describedby={statusId}>
        <label className="assistant-composer-label" htmlFor={messageId}>{t('ai.message')}</label>
        <textarea id={messageId} ref={textInput} name="message" value={draft} required maxLength={8000 - targetPrefix.length} rows={4} disabled={busy || !configured} onChange={event => {setDraft(event.target.value); setError('');}} placeholder={t('ai.placeholder')} onKeyDown={event => {if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {event.preventDefault(); event.currentTarget.form?.requestSubmit();}}}/>
        <div id={statusId} aria-live="polite" className="assistant-feedback">
          {error && <p className="error" role="alert">{error}</p>}
          {notice && <output className="ai-help">{notice}</output>}
          {messages.length > history.length && <p className="ai-help">{t('ai.historyLimit', {count: history.length})}</p>}
        </div>
        <footer className="assistant-composer-footer"><p className="ai-help">{includeWorkspace ? t(settings?.active_profile === 'local' ? 'ai.sentLocal' : 'ai.sentCloud') : t('ai.messagesOnly')}</p>
          {busy ? <Button key="cancel-request" type="button" variant="outline" onClick={cancel}><Square size={14}/>{t('ai.cancel')}</Button> : <Button key="send-message" type="submit" disabled={!draft.trim() || !configured || invalidSelection}><ArrowUp size={16}/>{t(error ? 'common.retry' : 'ai.send')}</Button>}
        </footer>
      </form>
    </section>
    <aside className="assistant-controls">
      <section className="panel assistant-context">
        <label className="check-label assistant-workspace-switch" htmlFor={includeId}><input id={includeId} type="checkbox" checked={includeWorkspace} disabled={busy} onChange={event => changeScope({include: event.target.checked})}/>{t('ai.workspace')}</label>
        {includeWorkspace && <>
          <Field label={t('ai.scope')}><select value={scope} disabled={busy} onChange={event => changeScope({scope: event.target.value as 'all' | 'selected'})}><option value="all">{t('ai.scopeAll')}</option><option value="selected">{t('ai.scopeSelected')}</option></select></Field>
          {scope === 'selected' && <div className="assistant-source-picker">
            <label className="assistant-source-search"><Search size={15}/><input aria-label={t('ai.sourceSearchLabel')} value={search} disabled={busy} placeholder={t('ai.sourceSearch')} onChange={event => setSearch(event.target.value)}/></label>
            <div className="assistant-selection-count"><span className="ai-help">{t('ai.selectedCount', {count: selectedIds.length})}</span>{!!selectedIds.length && <Button variant="ghost" disabled={busy} onClick={() => changeScope({ids: []})}>{t('ai.clearSelection')}</Button>}</div>
            <div className="assistant-source-list">{visibleContainers.map(container => <label key={container.id} aria-label={cultureText(container)}><input type="checkbox" checked={selectedIds.includes(container.id)} disabled={busy} onChange={event => changeScope({ids: event.target.checked ? [...selectedIds, container.id] : selectedIds.filter(id => id !== container.id)})}/><span><strong>{container.label || container.id}</strong><span>{cultureText(container).split(' · ').slice(1).join(' · ')}</span><small>{container.id} · {t(`status.${container.status}`)}</small></span></label>)}{!visibleContainers.length && <p className="ai-help">{t('ai.noContainers')}</p>}</div>
            {invalidSelection && <output className="ai-help warning-text">{t(missingSelection ? 'error.ai_container_not_found' : 'ai.noSelection')}</output>}
          </div>}
        </>}
      </section>
      <section className="panel assistant-target">
        <h2><CalendarDays size={17}/>{t('ai.targetDate')}</h2>
        <input aria-label={t('ai.targetDate')} name="target_date" form={composerId} type="date" value={targetDate} disabled={busy} onInput={event => setTargetDate(event.currentTarget.value)} onChange={event => setTargetDate(event.target.value)} onBlur={event => setTargetDate(event.currentTarget.value)}/>
        <div className="assistant-quick-actions"><Button variant="outline" disabled={busy || !configured} onClick={() => prefill('l1')}>{t('ai.l1')}</Button><Button variant="outline" disabled={busy || !configured} onClick={() => prefill('l3')}>{t('ai.l3')}</Button></div>
      </section>
    </aside>
  </div>;
}
