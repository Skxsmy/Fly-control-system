'use client';
import { useState } from 'react';
import { Button } from './ui/button';
import { Field, Form, Modal } from './fly-forms';
import { api } from '@/lib/api';
import { fmtDate, fmtNumber, fmtTime, t } from '@/lib/i18n';
import type { AppState, Culture, Task } from '@/lib/types';

type FormProps = {culture: Culture; state: AppState; close: () => void; saved: (id?: string) => Promise<void>};
const value = (form: FormData, key: string) => {const entry = form.get(key); return typeof entry === 'string' ? entry : '';};
export const isInjectionChild = (culture: Culture) => !!culture.injection && culture.injection.role !== 'source';

export function InjectionStartForm({culture, state, close, saved}: FormProps) {
  return <Modal title={t('injection.start')} description={culture.label} close={close}>
    <Form close={close} label={t('injection.begin')} submit={async form => {
      const result = await api<{source: Culture; bottle: Culture}>(`/containers/${culture.id}/injection-preparation`, 'POST', {
        at: value(form, 'at'), genotype: value(form, 'genotype'), notes: value(form, 'notes'),
      });
      await saved(result.source.id); close();
    }}>
      <p className="section-help">{t('injection.startHelp')}</p>
      {culture.temperature === 18 && <p className="notice warning">{t('error.injection_warm_source_first')}</p>}
      <Field label={t('injection.genotype')}><input name="genotype" required maxLength={1000} defaultValue={culture.purpose === 'cross' ? '' : culture.genotype}/></Field>
      <Field label={t('action.at')}><input name="at" type="datetime-local" required defaultValue={state.now.slice(0, 16)} min={`${culture.setup_date}T${culture.setup_time || '00:00'}`} max={state.now.slice(0, 16)}/></Field>
      <dl className="detail-facts"><div><dt>{t('injection.goal')}</dt><dd>{t('injection.target')}</dd></div></dl>
      <Field label={t('common.notes')}><textarea name="notes" rows={2} maxLength={10000}/></Field>
    </Form>
  </Modal>;
}

export function InjectionActionForm({culture, state, event, close, saved}: FormProps & {event: Task}) {
  const [females, setFemales] = useState('');
  const [males, setMales] = useState('');
  const [continuation, setContinuation] = useState('continue');
  const [at, setAt] = useState(state.now.slice(0, 16));
  const child = state.containers.find(c => c.source_id === culture.id && isInjectionChild(c));
  const ratio = Number(males) > 0 ? Number(females) / Number(males) : null;
  const outsideGoal = females !== '' && males !== '' && (Number(females) < 200 || ratio === null || Number(males) < Math.ceil(Number(females) / 4) || Number(males) > Math.ceil(Number(females) / 3));
  const earliest = culture.injection?.renewed_at || culture.injection?.transferred_at || culture.injection?.started_at || culture.injection?.initiated_at;
  return <Modal title={t(`task.${event.kind}`)} description={culture.label} close={close}>
    <Form close={close} label={t(event.kind === 'injection_collect' ? 'injection.finishCollection' : 'common.record')} submit={async form => {
      const result = await api<{container: Culture; bottle?: Culture; cage?: Culture}>(`/containers/${culture.id}/injection-actions`, 'POST', {
        action: event.kind, event_id: event.id, at: value(form, 'at'), notes: value(form, 'notes'),
        ...(event.kind === 'injection_collect' ? {female_count: Number(form.get('female_count')), male_count: Number(form.get('male_count'))} : {}),
        ...(event.kind === 'injection_embryos' ? {continue_collection: continuation === 'continue'} : {}),
      });
      await saved(result.cage?.id || result.bottle?.id || result.container.id); close();
    }}>
      {event.kind === 'injection_collect' && <>
        <p className="section-help">{t('injection.collectionHelp', {bottle: child?.label || t('injection.conditioning')})}</p>
        <p>{t('injection.target')}</p>
        <div className="form-grid">
          <Field label={t('injection.females')}><input name="female_count" type="number" min={0} max={1000000} step={1} required value={females} onChange={e => setFemales(e.target.value)}/></Field>
          <Field label={t('injection.males')}><input name="male_count" type="number" min={0} max={1000000} step={1} required value={males} onChange={e => setMales(e.target.value)}/></Field>
        </div>
        {ratio !== null && females !== '' && <output>{t('injection.ratio', {ratio: fmtNumber(ratio)})}</output>}
        {outsideGoal && <output className="notice warning">{t('injection.belowTarget')}</output>}
        <label className="check-label"><input type="checkbox" required/>{t('injection.yeastAdded')}</label>
      </>}
      {event.kind === 'injection_transfer' && <p className="notice warning">{t('injection.transferHelp', {bottle: culture.label, cage: child?.label || t('injection.newCage')})}</p>}
      {event.kind === 'injection_renew' && <p className="section-help">{t('injection.renewHelp')}</p>}
      {event.kind === 'injection_embryos' && <>
        <Field label={t('injection.afterCollection')}><select value={continuation} onChange={e => setContinuation(e.target.value)}>
          <option value="continue">{t('injection.continue')}</option><option value="stop">{t('injection.stop')}</option>
        </select></Field>
        <p className="section-help">{t(continuation === 'continue' ? 'injection.continueHelp' : 'injection.finishHelp')}</p>
      </>}
      <Field label={t('action.at')}><input name="at" type="datetime-local" required value={at} onChange={e => setAt(e.target.value)} min={earliest?.slice(0, 16)} max={state.now.slice(0, 16)}/></Field>
      <Field label={t('common.notes')}><textarea name="notes" rows={2} maxLength={10000}/></Field>
    </Form>
  </Modal>;
}

export function InjectionDetails({culture, state, select, perform}: {culture: Culture; state: AppState; select: (id: string) => void; perform: (event: Task) => void}) {
  const protocol = culture.injection;
  if (!protocol) return null;
  const parent = state.containers.find(c => c.id === culture.source_id);
  const root = protocol.role === 'source' ? culture : protocol.role === 'conditioning' ? parent : state.containers.find(c => c.id === parent?.source_id);
  const bottle = state.containers.find(c => c.source_id === root?.id && c.injection?.role === 'conditioning');
  const cage = state.containers.find(c => c.source_id === bottle?.id && c.injection?.role === 'cage');
  const pending = state.events.filter(e => e.container_id === culture.id && e.kind.startsWith('injection_') && e.status === 'pending');
  const action = pending.find(e => e.due <= state.now && e.end >= state.now) || pending[0];
  const stopped = protocol.phase === 'finished' && ((protocol.role === 'source' && !protocol.started_at) || (protocol.role === 'conditioning' && culture.parents !== 'transferred'));
  return <section className="clock-panel injection-panel">
    <div className="panel-title"><h3>{t('injection.chain')}</h3><span className="pill neutral">{t(stopped ? 'injection.stopped' : protocol.phase === 'finished' ? `injection.finished.${protocol.role}` : `injection.phase.${protocol.phase}`)}</span></div>
    <dl className="detail-facts">{[root, bottle, cage].map((c, index) => c && <div key={c.id}>
      <dt>{t(['injection.source', 'injection.conditioning', 'injection.cage'][index])}</dt>
      <dd>{c.id === culture.id ? <strong>{c.label}</strong> : <button className="text-link" onClick={() => select(c.id)}>{c.label}</button>} · {t(`status.${c.status}`)}</dd>
    </div>)}</dl>
    {protocol.female_count !== null && protocol.male_count !== null ? <p>{t('injection.counts', {female: protocol.female_count, male: protocol.male_count})}</p> : <p>{t('injection.target')}</p>}
    {protocol.started_at && <p>{t('injection.started')}: {fmtDate(protocol.started_at)} · {fmtTime(protocol.started_at)}</p>}
    {protocol.role === 'conditioning' && protocol.started_at && !cage && culture.status === 'active' && <p className="subtle">{t('injection.pendingCage')}</p>}
    {protocol.role === 'cage' && protocol.cycle > 0 && <p>{t('injection.cycle', {cycle: protocol.cycle})}</p>}
    {action && culture.status === 'active' && <Button onClick={() => perform(action)}>{t(`task.${action.kind}`)}</Button>}
  </section>;
}
