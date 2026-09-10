'use client';
import { useId, useState, useRef, type ReactNode, type SubmitEvent } from 'react';
import { X, Plus, ArrowRight } from 'lucide-react';
import { Dialog, DialogContent, DialogTitle, DialogDescription, DialogClose } from './ui/dialog';
import { Button } from './ui/button';
import { api } from '@/lib/api';
import { endAfterMove } from '@/lib/reminder-window';
import { WorkflowFields, workflowFrom } from './workflow-fields';
import { VirginCollectionGuidance } from './virgin-collection-guidance';
import { BackupPanel, type RestoreResult } from './backup-panel';
import { AISettings } from './ai-settings';
import { t, fmtDate, fmtTime, fmtNumber, weekday, availableLocales } from '@/lib/i18n';
import type { AppState, Culture, Task, Template, Settings, Suggestions, EggBatch, Incubation, Workflow } from '@/lib/types';

export function Modal({title, description, children, close, wide = false}: {title: string; description?: string; children: ReactNode; close: () => void; wide?: boolean}) {
  return <Dialog open onOpenChange={open => !open && close()}><DialogContent showCloseButton={false} className={`fly-dialog ${wide ? 'wide' : ''}`}>
    <header className="dialog-heading"><div><DialogTitle>{title}</DialogTitle>{description && <DialogDescription>{description}</DialogDescription>}</div>
      <DialogClose render={<Button variant="ghost" size="icon" aria-label={t('common.close')} />}><X size={20}/></DialogClose></header>{children}
  </DialogContent></Dialog>;
}

export function Field({label, hint, children}: {label: string; hint?: string; children: ReactNode}) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

export function Form({submit, children, label, close, destructive = false}: {submit: (data: FormData) => Promise<unknown>; children: ReactNode; label?: string; close?: () => void; destructive?: boolean}) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const errorId = useId();
  async function onSubmit(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault(); if (busy) return; const form = event.currentTarget;
    setBusy(true); setError('');
    try { await submit(new FormData(form)); } catch (e) { setError(e instanceof Error ? e.message : t('error.generic')); }
    finally { setBusy(false); }
  }
  return <form onSubmit={onSubmit} className="fly-form" aria-busy={busy} aria-describedby={error ? errorId : undefined}>
    {children}{error && <p id={errorId} className="error" role="alert">{error}</p>}
    <footer className="form-footer">{close && <Button type="button" variant="outline" onClick={close}>{t('common.cancel')}</Button>}<Button type="submit" variant={destructive ? 'destructive' : 'default'} disabled={busy}>{label || t('common.save')}{busy ? <span className="spinner"/> : <ArrowRight size={16}/>}</Button></footer>
  </form>;
}

export function parseWindows(value: string) {
  if (!value.trim()) return [];
  const pairs = value.split(',').map(x => x.trim().split(/\s*[–—-]\s*/));
  if (pairs.some((p, i) => p.length !== 2 || p.some(x => !/^([01]\d|2[0-3]):[0-5]\d$/.test(x)) || p[0] >= p[1] || (i > 0 && p[0] < pairs[i - 1][1]))) throw new Error(t('error.invalid_windows'));
  return pairs;
}
export const windowsText = (windows: string[][]) => windows.map(pair => pair.join('–')).join(', ');
function fieldValue(form: FormData, key: string) {const value = form.get(key); return typeof value === 'string' ? value : '';}

const templateNumbers: (keyof Template)[] = ['transfer_day', 'max_transfers', 'check_day', 'watch_day', 'collection_day', 'stock_interval', 'rate18', 'virgin_hours25', 'virgin_hours18'];
export function ProtocolFields({template, purpose, goal}: {template: Template; purpose?: Culture['purpose']; goal?: Workflow['cross_goal']}) {
  const collection = !purpose || purpose === 'virgin' || (purpose === 'cross' && (!goal || goal === 'virgins'));
  const larvae = purpose === 'larvae' || (purpose === 'cross' && goal === 'third_instar');
  const keys = templateNumbers.filter(key => !larvae || ['transfer_day','max_transfers'].includes(key)).filter(key => !purpose || (key === 'stock_interval' ? purpose === 'stock' : ['collection_day','virgin_hours25','virgin_hours18'].includes(key) ? collection : key === 'watch_day' ? purpose !== 'stock' : true));
  return <div className="protocol-fields"><div className="form-grid">{keys.map(key => <Field key={key} label={t(`settings.${key}`)} hint={key === 'rate18' ? t('settings.rate18Help') : undefined}><input name={`template.${key}`} type="number" required min={key === 'max_transfers' ? 0 : key === 'rate18' ? 0.01 : 1} max={key === 'rate18' ? 0.99 : undefined} step={key === 'rate18' ? 0.01 : 1} defaultValue={template[key] as number}/></Field>)}</div>
    {collection && <Field label={t('settings.windows')}><input name="template.windows" placeholder={t('calendar.windowsPlaceholder')} defaultValue={windowsText(template.windows)} required/></Field>}</div>;
}
export function templateFrom(form: FormData, base?: Template): Template {
  const result: Record<string, unknown> = {...base, collection_days: 1};
  templateNumbers.forEach(key => {if (form.has(`template.${key}`)) result[key] = Number(form.get(`template.${key}`));});
  if (form.has('template.windows')) result.windows = parseWindows(fieldValue(form, 'template.windows'));
  return result as Template;
}

function IncubationFields({value, batch, now}: {value?: Incubation; batch?: EggBatch; now: string}) {
  return <section className="form-section"><h3>{t('eggs.incubation')}</h3><div className="form-grid">
    <Field label={t('eggs.start')}><input name="lay_start" type="datetime-local" required readOnly={!!batch} defaultValue={(batch?.lay_start || value?.lay_start || now).slice(0,16)}/></Field>
    <Field label={t('eggs.end')}><input name="lay_end" type="datetime-local" required readOnly={!!batch} defaultValue={(batch?.lay_end || value?.lay_end || now).slice(0,16)}/></Field>
    <Field label={t('eggs.minHours')}><input name="min_hours" type="number" required min={0} max={720} step={0.25} defaultValue={value?.min_hours ?? 24}/></Field>
    <Field label={t('eggs.maxHours')}><input name="max_hours" type="number" required min={0.25} max={720} step={0.25} defaultValue={value?.max_hours ?? 30}/></Field>
    <Field label={t('eggs.referenceTemperature')}><select name="reference_temperature" defaultValue={value?.reference_temperature || 25}><option value="25">25°C</option><option value="18">18°C</option></select></Field>
    <Field label={t('eggs.layTemperature')}><select name="lay_temperature" defaultValue={batch?.temperature || value?.lay_temperature || 25} disabled={!!batch}><option value="25">25°C</option><option value="18">18°C</option></select></Field>
  </div></section>;
}
function incubationFrom(form: FormData): Incubation {
  return {lay_start: fieldValue(form,'lay_start'), lay_end:fieldValue(form,'lay_end'), min_hours:Number(form.get('min_hours')), max_hours:Number(form.get('max_hours')), reference_temperature:Number(form.get('reference_temperature')), lay_temperature:Number(form.get('lay_temperature') || 25)};
}

export function EggBatchForm({culture, now, close, saved}: {culture: Culture; now: string; close: () => void; saved: () => Promise<void>}) {
  return <Modal title={`${t('eggs.new')} · ${culture.label}`} close={close}><Form close={close} submit={async form => {
    await api(`/containers/${culture.id}/egg-batches`, 'POST', {label:fieldValue(form,'label'), genotype:fieldValue(form,'genotype'), lay_start:fieldValue(form,'lay_start'), lay_end:fieldValue(form,'lay_end'), temperature:Number(form.get('temperature')), notes:fieldValue(form,'notes')}); await saved(); close();
  }}>
    <Field label={t('eggs.label')}><input name="label" required maxLength={80}/></Field>
    <Field label={t('container.genotype')}><input name="genotype" required defaultValue={culture.genotype}/></Field>
    <Field label={t('eggs.start')}><input name="lay_start" type="datetime-local" required defaultValue={now.slice(0,16)} min={`${culture.setup_date}T${culture.setup_time || '00:00'}`}/></Field>
    <Field label={t('eggs.end')}><input name="lay_end" type="datetime-local" required defaultValue={now.slice(0,16)}/></Field>
    <Field label={t('eggs.layTemperature')}><select name="temperature" defaultValue={culture.temperature}><option value="25">25°C</option><option value="18">18°C</option></select></Field>
    <Field label={t('common.notes')}><textarea name="notes" rows={2}/></Field>
  </Form></Modal>;
}

export function EggActionForm({batch, action, now, close, saved}: {batch: EggBatch; action:'collect'|'use'|'cancel'; now:string; close:()=>void; saved:()=>Promise<void>}) {
  return <Modal title={`${t(`eggs.${action}`)} · ${batch.label}`} close={close}><Form close={close} label={t('common.record')} submit={async form => {
    await api(`/egg-batches/${batch.id}/actions`, 'POST', {action, at:fieldValue(form,'at'), purpose:fieldValue(form,'purpose') || 'other', notes:fieldValue(form,'notes')}); await saved(); close();
  }}>
    <Field label={t('action.at')}><input name="at" type="datetime-local" required defaultValue={now.slice(0,16)} max={now.slice(0,16)} min={(action === 'collect' ? batch.lay_end : action === 'use' ? batch.collected_at || batch.lay_end : batch.lay_start).slice(0,16)}/></Field>
    {action === 'use' && <Field label={t('container.purpose')}><select name="purpose">{['imaging','dissection','other'].map(x => <option key={x} value={x}>{t(`purpose.${x}`)}</option>)}</select></Field>}
    <Field label={t('common.notes')}><textarea name="notes" rows={2}/></Field>
  </Form></Modal>;
}

export function ContainerForm({state, source, mode, eggBatch, close, saved}: {state: AppState; source?: Culture; mode?: 'transfer' | 'generation' | 'edit'; eggBatch?: EggBatch; close: () => void; saved: (id?: string) => Promise<void>}) {
  const [purpose, setPurpose] = useState<Culture['purpose']>(source?.purpose || (eggBatch ? 'dissection' : 'cross'));
  const [kind, setKind] = useState<Culture['kind']>(source?.kind || (eggBatch ? 'petri_dish' : 'vial'));
  const [batchId, setBatchId] = useState(eggBatch?.id || source?.egg_batch_id || '');
  const batch = kind === 'petri_dish' ? state.egg_batches.find(b => b.id === batchId) : undefined;
  const hourly = kind === 'petri_dish' || kind === 'egg_laying';
  const edit = mode === 'edit';
  const editableStart = !edit || source?.status === 'planned' || (kind === 'egg_laying' && source?.setup_time_review_required);
  const [useWorkflow, setUseWorkflow] = useState(!edit || !!source?.workflow);
  const [crossGoal, setCrossGoal] = useState<Workflow['cross_goal']>(source?.workflow?.cross_goal || (edit ? 'virgins' : 'score'));
  return <Modal title={t(edit ? 'container.edit' : mode === 'transfer' ? 'container.transfer' : mode === 'generation' ? 'container.nextGeneration' : 'common.newContainer')} description={source ? edit ? source.label : `${t('container.source')}: ${source.label}` : undefined} close={close} wide>
    <Form close={close} label={t(edit ? 'common.save' : 'common.create')} submit={async form => {
      const payload = {label: fieldValue(form, 'label'), kind, purpose, genotype: (fieldValue(form, 'genotype') || ''), female_genotype: (fieldValue(form, 'female_genotype') || ''), male_genotype: (fieldValue(form, 'male_genotype') || ''),
        ...(editableStart ? {setup_date: fieldValue(form, 'setup_date'), setup_time: (fieldValue(form, 'setup_time') || '') || null} : {}), initial_temperature: Number(form.get('initial_temperature')),
        temperature_policy: fieldValue(form, 'temperature_policy'), notes: fieldValue(form, 'notes'), template: hourly ? source?.template || state.settings.template : templateFrom(form, source?.template || state.settings.template), ...(!hourly && useWorkflow ? {workflow:workflowFrom(form,crossGoal,source?.workflow)} : {}), ...(kind === 'petri_dish' ? {incubation: incubationFrom(form), egg_batch_id: batchId || null} : {}), ...(mode ? {mode} : {initial_status: fieldValue(form, 'initial_status'), parents: kind === 'petri_dish' ? 'removed' : fieldValue(form, 'parents'), stage: fieldValue(form, 'stage'), transfer_index: Number(form.get('transfer_index'))})};
      const result = await api<Culture>(edit ? `/containers/${source!.id}` : mode ? `/containers/${source!.id}/transfer` : '/containers', edit ? 'PUT' : 'POST', payload);
      await saved(result.id); close();
    }}>
      <div className="form-grid"><Field label={t('container.id')}><input name="label" placeholder={edit ? undefined : t('container.autoIdPlaceholder')} defaultValue={edit ? source?.label : ''} required={edit} maxLength={80}/></Field>
        {!edit && <Field label={t('container.type')}><select value={kind} onChange={e => {const next = e.target.value as Culture['kind']; setKind(next); if (next !== 'petri_dish') setBatchId(''); setPurpose(next === 'egg_laying' ? 'egg_laying' : next === 'petri_dish' ? 'dissection' : source?.purpose || 'cross');}}>{(mode ? ['vial', 'bottle'] : ['vial', 'bottle', 'petri_dish', 'egg_laying']).map(x => <option key={x} value={x}>{t(`kind.${x}`)}</option>)}</select></Field>}
        {!edit && <Field label={t('container.purpose')}><select value={purpose} disabled={mode === 'transfer' || kind === 'egg_laying'} onChange={e => setPurpose(e.target.value as Culture['purpose'])}>{(kind === 'egg_laying' ? ['egg_laying'] : kind === 'petri_dish' ? ['dissection', 'imaging', 'other'] : ['cross', 'stock', 'virgin', 'larvae']).map(x => <option key={x} value={x}>{t(`purpose.${x}`)}</option>)}</select></Field>}
        {!edit && <Field label={t('container.initialTemperature')}><select name="initial_temperature" defaultValue={source?.temperature || 25}><option value="25">25°C</option><option value="18">18°C</option></select></Field>}
      </div>
      {kind === 'petri_dish' && !edit && <Field label={t('eggs.source')}><select value={batchId} onChange={e => setBatchId(e.target.value)}><option value="">{t('eggs.external')}</option>{state.egg_batches.filter(b => b.status === 'collected').map(b => <option key={b.id} value={b.id}>{b.label}</option>)}</select></Field>}
      {purpose === 'cross' ? <div className="form-grid"><Field label={t('container.female')}><input name="female_genotype" required defaultValue={source?.female_genotype} readOnly={mode === 'transfer'} list="known-genotypes"/></Field><Field label={t('container.male')}><input name="male_genotype" required defaultValue={source?.male_genotype} readOnly={mode === 'transfer'} list="known-genotypes"/></Field></div> : <Field label={t(kind === 'egg_laying' ? 'eggs.knownGenotype' : 'container.genotype')}><input key={`${kind}-${batchId}`} name="genotype" required defaultValue={batch?.genotype || source?.genotype} readOnly={mode === 'transfer'} list="known-genotypes"/></Field>}
      <datalist id="known-genotypes">{[...new Set(state.containers.flatMap(c => [c.genotype, c.female_genotype, c.male_genotype]).filter(Boolean))].map(g => <option key={g} value={g} aria-label={g}/>)}</datalist>
      {editableStart && <div className="form-grid"><Field label={t(kind === 'petri_dish' ? 'eggs.dishSetup' : kind === 'egg_laying' ? 'eggs.startDate' : 'container.setup')}><input name="setup_date" type="date" defaultValue={edit ? source?.setup_date : state.now.slice(0, 10)} required max={mode && !edit ? state.now.slice(0, 10) : undefined}/></Field><Field label={`${t('container.setupTime')}${hourly ? '' : ` · ${t('common.optional')}`}`}><input name="setup_time" type="time" required={hourly} defaultValue={edit ? source?.setup_time || '' : mode || hourly ? state.now.slice(11, 16) : ''}/></Field></div>}
      {kind === 'egg_laying' && source?.genotype_review_required && <p className="notice warning">{t('eggs.genotypeReview')} {t('eggs.legacyGenotypes', {female:source.female_genotype, male:source.male_genotype})}</p>}
      {kind === 'egg_laying' && source?.setup_time_review_required && <p className="notice warning">{t('eggs.timeReview')}</p>}
      {kind === 'petri_dish' && <IncubationFields key={batchId} value={source?.incubation || undefined} batch={batch} now={state.now}/>}
      {!mode && <section className="form-section"><h3>{t('container.initialState')}</h3>{['vial','bottle'].includes(kind) && <p className="section-help">{t('container.initialStateHelp')}</p>}<div className="form-grid">
        <Field label={t('container.status')}><select name="initial_status" defaultValue="auto"><option value="auto">{t('container.autoStatus')}</option>{['active', 'planned'].map(x => <option key={x} value={x}>{t(`status.${x}`)}</option>)}</select></Field>
        {kind !== 'petri_dish' && <Field label={t('container.parentState')}><select name="parents" defaultValue="present">{['present', 'removed', 'transferred'].map(x => <option key={x} value={x}>{t(`parents.${x}`)}</option>)}</select></Field>}
        <Field label={t('container.stage')}><select name="stage" defaultValue="unobserved">{['unobserved', 'first_instar', 'larvae', 'pupae', 'eclosion'].map(x => <option key={x} value={x}>{t(`stage.${x}`)}</option>)}</select></Field>
        {kind !== 'petri_dish' && <Field label={t('container.initialTransfers')}><input name="transfer_index" type="number" min={0} max={20} step={1} defaultValue={0} required/></Field>}
      </div></section>}
      <Field label={t('temperature.policy')}><select name="temperature_policy" defaultValue={source?.temperature_policy || 'allowed'}><option value="allowed">{t('temperature.allowed')}</option><option value="forbidden">{t('temperature.forbidden')}</option></select></Field>
      <Field label={t('common.notes')}><textarea name="notes" rows={2} defaultValue={edit ? source?.notes : ''}/></Field>
      {!hourly && edit && !source?.workflow && <label className="check-label"><input type="checkbox" checked={useWorkflow} onChange={e => setUseWorkflow(e.target.checked)}/>{t('workflow.upgrade')}</label>}
      {!hourly && useWorkflow && <WorkflowFields key={purpose} purpose={purpose} value={source?.workflow} goal={crossGoal} setGoal={setCrossGoal}/>}
      {!hourly && <details className="form-section"><summary>{t('container.protocol')}</summary><ProtocolFields template={source?.template || state.settings.template} purpose={purpose} goal={useWorkflow ? crossGoal : 'virgins'}/></details>}
    </Form>
  </Modal>;
}

export function ActionForm({culture, action, event, now, close, saved}: {culture: Culture; action: string; event?: Task; now: string; close: () => void; saved: () => Promise<void>}) {
  const [actionTime, setActionTime] = useState(now.slice(0,16));
  return <Modal title={`${t(action === 'activate' && culture.kind === 'egg_laying' ? 'eggs.recordStart' : `action.${action}`)} · ${culture.label}`} close={close}>
    <Form close={close} label={t('common.record')} submit={async form => {
      await api(`/containers/${culture.id}/actions`, 'POST', {action, at: fieldValue(form, 'at'), cleared: form.get('cleared') === 'on', notes: fieldValue(form, 'notes'), event_id: event?.id});
      await saved(); close();
    }}>
      <Field label={t('action.at')}><input name="at" type="datetime-local" value={actionTime} onInput={e => setActionTime(e.currentTarget.value)} onChange={e => setActionTime(e.target.value)} required min={action === 'activate' ? undefined : `${culture.setup_date}T${culture.setup_time || '00:00'}`} max={now.slice(0, 16)}/></Field>
      {action === 'collect' && <VirginCollectionGuidance culture={culture} now={now} actionTime={actionTime} compact/>}
      {action === 'score' && culture.workflow?.target_genotype && <dl className="detail-facts"><div><dt>{t('workflow.target')}</dt><dd>{culture.workflow.target_genotype}</dd></div></dl>}
      {action === 'collect' && <label className="check-label"><input name="cleared" type="checkbox"/>{t('action.cleared')}</label>}
      {action === 'clear' && <p className="notice">{t('action.clearHint')}</p>}
      {['complete', 'discard'].includes(action) && <p className="notice warning">{t('action.endHint')}</p>}
      <Field label={t('common.notes')}><textarea name="notes" rows={3}/></Field>
    </Form>
  </Modal>;
}

export function ReminderForm({state, event, cultureId, date, batch, close, saved}: {state: AppState; event?: Task; cultureId?: string; date?: string; batch?: EggBatch; close: () => void; saved: () => Promise<void>}) {
  const [start, setStart] = useState(event?.due.slice(0, 16) || `${date || state.now.slice(0, 10)}T09:00`);
  const [end, setEnd] = useState(event?.end.slice(0, 16) || `${date || state.now.slice(0, 10)}T09:30`);
  const original = useRef({start, end});
  const [keepDuration, setKeepDuration] = useState(!!event);
  function moveStart(value: string) {
    const next = endAfterMove(value, original.current.start, original.current.end);
    if (keepDuration && next) setEnd(next);
    setStart(value);
  }
  return <Modal title={t(event ? 'task.move' : 'common.newTask')} description={event ? [state.containers.find(c => c.id === event.container_id)?.label, event.title || t(`task.${event.kind}`), event.batch_label].filter(Boolean).join(' · ') : undefined} close={close}>
    <Form close={close} submit={async form => {
      const due = fieldValue(form, 'due');
      const body = {title: fieldValue(form, 'title'), container_id: batch?.source_id || (fieldValue(form, 'container_id') || '') || null, egg_batch_id: batch?.id, due, end: keepDuration ? endAfterMove(due, original.current.start, original.current.end) : fieldValue(form, 'end'), critical: form.get('critical') === 'on'};
      await api(event ? `/events/${event.id}` : '/events', event ? 'PATCH' : 'POST', body); await saved(); close();
    }}>
      {!event && <><Field label={t('task.title')}><input name="title" required maxLength={200} defaultValue={batch ? `${t('purpose.imaging')} · ${batch.label}` : ''}/></Field><Field label={t('container.id')}><select name="container_id" disabled={!!batch} defaultValue={batch?.source_id || cultureId || ''}><option value="">{t('task.general')}</option>{state.containers.filter(c => ['active', 'planned'].includes(c.status)).map(c => <option key={c.id} value={c.id}>{c.label}</option>)}</select></Field></>}
      {event && <><p className="section-help">{t('task.rescheduleHelp')}</p><label className="check-label"><input type="checkbox" checked={keepDuration} onChange={e => setKeepDuration(e.target.checked)}/>{t('task.keepDuration')}</label></>}
      <Field label={t('task.start')}><input name="due" type="datetime-local" value={start} onChange={e => moveStart(e.target.value)} onInput={e => moveStart(e.currentTarget.value)} onBlur={e => moveStart(e.target.value)} required/></Field>
      <Field label={t('task.end')}><input name="end" type="datetime-local" value={end} readOnly={keepDuration} onChange={e => setEnd(e.target.value)} required min={start}/></Field>
      {!event && <label className="check-label"><input name="critical" type="checkbox"/>{t('task.critical')}</label>}
    </Form>
  </Modal>;
}

export function AvailabilityForm({state, day, close, saved}: {state: AppState; day: string; close: () => void; saved: () => Promise<void>}) {
  const existing = state.availability.find(x => x.date === day);
  const [kind, setKind] = useState(existing?.kind || 'workday');
  const index = (new Date(day + 'T12:00').getDay() + 6) % 7;
  return <Modal title={t('calendar.availability')} description={fmtDate(day, {weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'})} close={close}>
    <Form close={close} submit={async form => {
      await api('/availability', 'PUT', {date: day, kind, windows: ['workday', 'partial'].includes(kind) ? parseWindows(fieldValue(form, 'windows')) : [], notes: fieldValue(form, 'notes')});
      await saved(); close();
    }}><Field label={t('calendar.kind')}><select value={kind} onChange={e => setKind(e.target.value)}>{['workday', 'rest', 'holiday', 'leave', 'blocked', 'partial'].map(x => <option key={x} value={x}>{t(`availability.${x}`)}</option>)}</select></Field>
      {['workday', 'partial'].includes(kind) && <Field label={t('calendar.windows')}><input name="windows" placeholder={t('calendar.windowsPlaceholder')} defaultValue={windowsText(existing?.windows || state.settings.weekly[String(index)])}/></Field>}
      <Field label={t('common.notes')}><textarea name="notes" rows={2} defaultValue={existing?.notes}/></Field>
      {existing && <Button type="button" variant="outline" onClick={async () => {await api(`/availability/${day}`, 'DELETE'); await saved(); close();}}>{t('common.reset')}</Button>}
    </Form>
  </Modal>;
}

export function Planner({culture, close, saved}: {culture: Culture; close: () => void; saved: () => Promise<void>}) {
  const [result, setResult] = useState<Suggestions | null>(null); const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  const planned = culture.status === 'planned';
  async function find() {setBusy(true); setError(''); try {setResult(await api<Suggestions>(`/containers/${culture.id}/suggestions`));} catch (e) {setError((e as Error).message);} finally {setBusy(false);}}
  return <Modal title={`${t(planned ? 'planner.setupTitle' : 'planner.title')} · ${culture.label}`} close={close} wide>
    {!result && <Button disabled={busy} onClick={find}>{t(planned ? 'planner.setupFind' : 'planner.open')}{busy && <span className="spinner"/>}</Button>}
    {result && !['suggested', 'setup_suggested'].includes(result.state) && <p className="notice warning">{t(`planner.${result.state}`)}</p>}
    {result?.options.map((option, i) => option.setup_at ? <div className="plan-option" key={i}><h3>{fmtDate(option.setup_at, {weekday: 'long', month: 'short', day: 'numeric'})} · {fmtTime(option.setup_at)}</h3><Button disabled={busy} onClick={async () => {setBusy(true); try {await api(`/containers/${culture.id}/setup-plan`, 'POST', {setup_at: option.setup_at}); await saved(); close();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}}}>{t('planner.setupAccept')}</Button></div> : <div className="plan-option" key={i}><h3>{t('planner.hours', {hours: fmtNumber(option.hours)})}</h3>
      <dl><div><dt>{t('task.cold')}</dt><dd>{fmtDate(option.cold_at, {weekday: 'short', month: 'short', day: 'numeric'})} · {fmtTime(option.cold_at)}</dd></div><div><dt>{t('task.warm')}</dt><dd>{fmtDate(option.warm_at, {weekday: 'short', month: 'short', day: 'numeric'})} · {fmtTime(option.warm_at)}</dd></div><div><dt>{t('planner.collection')}</dt><dd>{fmtDate(option.collection_date, {weekday: 'long', month: 'short', day: 'numeric'})}</dd></div></dl>
      <Button disabled={busy} onClick={async () => {setBusy(true); try {await api(`/containers/${culture.id}/plans`, 'POST', option); await saved(); close();} catch(e) {setError((e as Error).message);} finally {setBusy(false);}}}><Plus size={16}/>{t('planner.accept')}</Button></div>)}
    {error && <p className="error" role="alert">{error}</p>}
  </Modal>;
}

function ShutdownPanel({onShutdown}: {onShutdown: () => void}) {
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);
  return <section className="panel"><h2>{t('runtime.title')}</h2><p className="section-help">{t('runtime.help')}</p><Button disabled={busy} variant="outline" onClick={async () => {setBusy(true); setError(''); try {const runtime = await api<{managed:boolean; token:string}>('/runtime'); if (!runtime.managed) throw new Error(t('error.shutdown_unavailable')); await api('/shutdown','POST',{token:runtime.token}); onShutdown();} catch(e) {setError((e as Error).message); setBusy(false);}}}>{t('runtime.stop')}</Button>{error && <p className="error" role="alert">{error}</p>}</section>;
}

export type SettingsSection = 'general' | 'backup' | 'ai';
export function SettingsPage({settings, saved, onShutdown, section, onSectionChange, onRestored}: {settings: Settings; saved: () => Promise<void>; onShutdown: () => void; section: SettingsSection; onSectionChange: (section: SettingsSection) => void; onRestored: (result: RestoreResult) => Promise<void>}) {
  return <div className="settings-page"><fieldset className="settings-sections" aria-label={t('settings.sections')}>
    {(['general', 'backup', 'ai'] as const).map(value => <Button key={value} variant={section === value ? 'default' : 'outline'} aria-pressed={section === value} onClick={() => onSectionChange(value)}>{t(`settings.${value}Tab`)}</Button>)}
  </fieldset>
    {section === 'general' && <GeneralSettingsPage key={JSON.stringify(settings)} settings={settings} saved={saved} onShutdown={onShutdown}/>}
    {section === 'backup' && <BackupPanel restored={onRestored}/>}
    {section === 'ai' && <AISettings/>}
  </div>;
}

function GeneralSettingsPage({settings, saved, onShutdown}: {settings: Settings; saved: () => Promise<void>; onShutdown: () => void}) {
  return <div className="settings-layout"><section className="panel"><div className="panel-title"><h2>{t('settings.protocol')}</h2></div><Form submit={async form => {
    const weekly: Record<string, string[][]> = {}; for (let i = 0; i < 7; i++) weekly[String(i)] = parseWindows(fieldValue(form, `weekly.${i}`));
    await api('/settings', 'PUT', {...settings, locale: (fieldValue(form, 'locale') || settings.locale), timezone: fieldValue(form, 'timezone'), weekly, template: templateFrom(form)}); await saved();
  }}><ProtocolFields template={settings.template}/>
    <section className="form-section"><h2>{t('calendar.weekly')}</h2>{Array.from({length: 7}, (_, i) => <Field key={i} label={weekday(i)}><input name={`weekly.${i}`} placeholder={t('calendar.windowsPlaceholder')} defaultValue={windowsText(settings.weekly[String(i)])}/></Field>)}</section>
    <section className="form-section"><h2>{t('settings.general')}</h2><Field label={t('settings.timezone')}><input name="timezone" defaultValue={settings.timezone} required/></Field><Field label={t('common.language')}><select name="locale" defaultValue={settings.locale}>{availableLocales().map(locale => <option key={locale.code} value={locale.code}>{locale.name}</option>)}</select></Field></section>
  </Form></section><aside className="settings-aside"><ShutdownPanel onShutdown={onShutdown}/></aside></div>;
}
