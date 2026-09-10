'use client';
import { useState } from 'react';
import { Field, Form, Modal } from './fly-forms';
import { api } from '@/lib/api';
import { t } from '@/lib/i18n';
import type { AppState, Culture } from '@/lib/types';

export function EggLayingFromForm({source, state, close, saved}: {
  source: Culture; state: AppState; close: () => void; saved: (id?: string) => Promise<void>;
}) {
  const [mode, setMode] = useState('');
  const canTransfer = source.parents === 'present' && source.transfer_index < source.template.max_transfers;
  const cross = source.purpose === 'cross';
  const female = cross ? (mode === 'transfer' ? source.female_genotype : '') : source.genotype;
  const male = cross ? (mode === 'transfer' ? source.male_genotype : '') : source.genotype;
  const value = (form: FormData, key: string) => {const entry = form.get(key); return typeof entry === 'string' ? entry : '';};
  return <Modal title={t('eggs.fromContainer')} description={t('eggs.fromHint', {source: source.label})} close={close} wide>
    <Form close={close} label={t('common.create')} submit={async form => {
      const result = await api<Culture>(`/containers/${source.id}/egg-laying`, 'POST', {
        cohort_mode: mode, label: value(form, 'label'),
        female_genotype: value(form, 'female_genotype'), male_genotype: value(form, 'male_genotype'),
        setup_date: value(form, 'setup_date'), setup_time: value(form, 'setup_time') || null,
        initial_temperature: value(form, 'initial_temperature') === 'inherit' ? null : Number(form.get('initial_temperature')),
        temperature_policy: value(form, 'temperature_policy'), notes: value(form, 'notes'),
      });
      await saved(result.id); close();
    }}>
      <Field label={t('eggs.adultSource')}>
        <select required value={mode} onChange={e => setMode(e.target.value)}>
          <option value="" disabled>{t('eggs.chooseAdults')}</option>
          <option value="transfer" disabled={!canTransfer}>{t('eggs.moveParents')}</option>
          <option value="generation">{t('eggs.selectOffspring')}</option>
        </select>
      </Field>
      {!canTransfer && <p className="subtle">{t('error.transfer_unavailable')}</p>}
      {mode && <>
        <p className="notice">{t(mode === 'transfer' ? 'eggs.moveHint' : 'eggs.offspringHint', {count: source.transfer_index + 1})}</p>
        <div className="form-grid">
          <Field label={t('container.id')} hint={t('container.autoId')}><input name="label" maxLength={80}/></Field>
          <Field label={t('container.initialTemperature')} hint={t('eggs.sourceTemperatureHint')}><select name="initial_temperature" defaultValue="inherit"><option value="inherit">{t('eggs.sourceTemperature')}</option><option value="25">25°C</option><option value="18">18°C</option></select></Field>
        </div>
        <p className="subtle">{t(cross && mode === 'generation' ? 'eggs.offspringGenotypeHint' : 'eggs.inheritedGenotypeHint')}</p>
        <div className="form-grid" key={mode}>
          <Field label={t('container.female')}><input name="female_genotype" required maxLength={1000} defaultValue={female} list="egg-parent-genotypes"/></Field>
          <Field label={t('container.male')}><input name="male_genotype" required maxLength={1000} defaultValue={male} list="egg-parent-genotypes"/></Field>
        </div>
        <datalist id="egg-parent-genotypes">{[...new Set(state.containers.flatMap(c => [c.genotype, c.female_genotype, c.male_genotype]).filter(Boolean))].map(g => <option key={g} value={g} aria-label={g}/>)}</datalist>
        <div className="form-grid">
          <Field label={t('container.setup')}><input name="setup_date" type="date" required min={source.setup_date} max={state.now.slice(0,10)} defaultValue={state.now.slice(0,10)}/></Field>
          <Field label={`${t('container.setupTime')} · ${t('common.optional')}`}><input name="setup_time" type="time" defaultValue={state.now.slice(11,16)}/></Field>
        </div>
        <Field label={t('temperature.policy')}><select name="temperature_policy" defaultValue={source.temperature_policy}><option value="allowed">{t('temperature.allowed')}</option><option value="forbidden">{t('temperature.forbidden')}</option></select></Field>
        <Field label={t('common.notes')} hint={t('eggs.copiedNotesHint')}><textarea name="notes" rows={3} maxLength={10000} defaultValue={source.notes}/></Field>
      </>}
    </Form>
  </Modal>;
}
