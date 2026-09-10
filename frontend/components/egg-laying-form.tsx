'use client';
import { useState } from 'react';
import { Field, Form, Modal } from './fly-forms';
import { EggSourceEstimate } from './egg-source-estimate';
import { api } from '@/lib/api';
import { t } from '@/lib/i18n';
import type { AppState, Culture } from '@/lib/types';

export function EggLayingFromForm({source, state, close, saved}: {
  source: Culture; state: AppState; close: () => void; saved: (id?: string) => Promise<void>;
}) {
  const [adultSource, setAdultSource] = useState('');
  const [status, setStatus] = useState('active');
  const [startDate, setStartDate] = useState(state.now.slice(0, 10));
  const [startTime, setStartTime] = useState(state.now.slice(11, 16));
  const value = (form: FormData, key: string) => {const entry = form.get(key); return typeof entry === 'string' ? entry : '';};
  function chooseAdults(next: string) {
    setAdultSource(next);
    setStatus(next === 'offspring' ? 'planned' : 'active');
    const estimate = next === 'offspring' ? source.eclosion_estimate?.at : undefined;
    const start = estimate && estimate > state.now ? estimate : state.now;
    setStartDate(start.slice(0, 10)); setStartTime(next === 'offspring' ? '' : start.slice(11, 16));
  }
  return <Modal title={t('eggs.fromContainer')} description={t('eggs.fromHint', {source: source.label})} close={close} wide>
    <Form close={close} label={t('common.create')} submit={async form => {
      const result = await api<Culture>(`/containers/${source.id}/egg-laying`, 'POST', {
        adult_source: adultSource, label: value(form, 'label'), genotype: value(form, 'genotype'),
        setup_date: value(form, 'setup_date'), setup_time: value(form, 'setup_time'), initial_status: status,
        initial_temperature: value(form, 'initial_temperature') === 'inherit' ? null : Number(form.get('initial_temperature')),
        temperature_policy: value(form, 'temperature_policy'), notes: value(form, 'notes'),
      });
      await saved(result.id); close();
    }}>
      <Field label={t('eggs.adultSource')}>
        <select required value={adultSource} onChange={e => chooseAdults(e.target.value)}>
          <option value="" disabled>{t('eggs.chooseAdults')}</option>
          <option value="parents" disabled={source.status === 'planned'}>{t('eggs.moveParents')}</option>
          <option value="offspring">{t('eggs.selectOffspring')}</option>
        </select>
      </Field>
      {adultSource && <>
        <p className="notice">{t('eggs.selectedAdultsHint')}</p>
        {adultSource === 'offspring' && <EggSourceEstimate estimate={source.eclosion_estimate}/>}
        <Field label={t('eggs.knownGenotype')} hint={t(source.purpose === 'cross' ? 'eggs.offspringGenotypeHint' : 'eggs.inheritedGenotypeHint')}>
          <input key={adultSource} name="genotype" required maxLength={1000} defaultValue={source.purpose === 'cross' ? '' : source.genotype} list="egg-known-genotypes"/>
        </Field>
        <datalist id="egg-known-genotypes">{[...new Set(state.containers.map(c => c.genotype).filter(Boolean))].map(g => <option key={g} value={g} aria-label={g}/>)}</datalist>
        <section className="form-section">
          <h3>{t('eggs.startHeading')}</h3>
          <Field label={t('eggs.startStatus')}><select value={status} onChange={e => setStatus(e.target.value)}>
            <option value="active" disabled={source.status === 'planned'}>{t('eggs.started')}</option>
            <option value="planned">{t('eggs.planned')}</option>
          </select></Field>
          <div className="form-grid">
            <Field label={t(status === 'planned' ? 'eggs.plannedStartDate' : 'eggs.actualStartDate')}><input name="setup_date" type="date" required min={source.setup_date} max={status === 'active' ? state.now.slice(0,10) : undefined} value={startDate} onInput={e => setStartDate(e.currentTarget.value)} onChange={e => setStartDate(e.target.value)}/></Field>
            <Field label={t(status === 'planned' ? 'eggs.plannedStartTime' : 'eggs.actualStartTime')}><input name="setup_time" type="time" required value={startTime} onInput={e => setStartTime(e.currentTarget.value)} onChange={e => setStartTime(e.target.value)}/></Field>
          </div>
          <p className="subtle">{t(status === 'planned' ? 'eggs.plannedHint' : 'eggs.actualHint')}</p>
        </section>
        <div className="form-grid">
          <Field label={t('container.id')} hint={t('container.autoId')}><input name="label" maxLength={80}/></Field>
          <Field label={t('container.initialTemperature')} hint={t('eggs.sourceTemperatureHint')}><select name="initial_temperature" defaultValue="inherit"><option value="inherit">{t('eggs.sourceTemperature')}</option><option value="25">25°C</option><option value="18">18°C</option></select></Field>
        </div>
        <Field label={t('temperature.policy')}><select name="temperature_policy" defaultValue={source.temperature_policy}><option value="allowed">{t('temperature.allowed')}</option><option value="forbidden">{t('temperature.forbidden')}</option></select></Field>
        <Field label={t('common.notes')} hint={t('eggs.copiedNotesHint')}><textarea name="notes" rows={3} maxLength={10000} defaultValue={source.notes}/></Field>
      </>}
    </Form>
  </Modal>;
}
