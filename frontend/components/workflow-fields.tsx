'use client';
import { t } from '@/lib/i18n';
import type { Culture, Workflow } from '@/lib/types';
import { Field } from './fly-forms';

export function WorkflowFields({purpose, value, goal, setGoal, defaultTransferEnabled}: {purpose: Culture['purpose']; value?: Workflow | null; goal: Workflow['cross_goal']; setGoal: (goal: Workflow['cross_goal']) => void; defaultTransferEnabled?: boolean}) {
  return <section className="form-section"><h3>{t('workflow.title')}</h3>
    {purpose === 'cross' && <>
      <Field label={t('workflow.goal')}><select value={goal} onChange={e => setGoal(e.target.value as Workflow['cross_goal'])}>{['score','virgins','third_instar'].map(x => <option key={x} value={x}>{t(`workflow.${x}`)}</option>)}</select></Field>
      <Field label={t('workflow.females')}><select name="workflow.female_virgins" defaultValue={value?.female_virgins || 'unconfirmed'}><option value="unconfirmed">{t('workflow.unconfirmed')}</option><option value="confirmed">{t('workflow.confirmed')}</option></select></Field>
      <Field label={t('workflow.target')}><input name="workflow.target_genotype" defaultValue={value?.target_genotype || ''} maxLength={1000}/></Field>
      <Field label={t('workflow.criteria')}><textarea name="workflow.selection_notes" defaultValue={value?.selection_notes || ''} maxLength={3000} rows={2}/></Field>
    </>}
    <label className="check-label"><input type="checkbox" name="workflow.transfer_enabled" defaultChecked={defaultTransferEnabled ?? value?.transfer_enabled ?? purpose !== 'stock'}/>{t('workflow.transfer')}</label>
    {purpose !== 'stock' && <Field label={t('workflow.removeDay')}><input name="workflow.remove_day" type="number" min={1} max={30} required defaultValue={value?.remove_day || 5}/></Field>}
    {purpose === 'cross' && goal === 'score' && <>
      <div className="form-grid"><Field label={t('workflow.selectionDay')}><input name="workflow.selection_day" type="number" min={1} max={90} required defaultValue={value?.selection_day || 10}/></Field>
      <Field label={t('workflow.selectionDays')}><input name="workflow.selection_days" type="number" min={1} max={14} required defaultValue={value?.selection_days || 1}/></Field>
      <Field label={t('workflow.selectionStart')}><input name="workflow.selection_start" type="time" required defaultValue={value?.selection_window[0] || '09:00'}/></Field>
      <Field label={t('workflow.selectionEnd')}><input name="workflow.selection_end" type="time" required defaultValue={value?.selection_window[1] || '17:00'}/></Field></div>
      <label className="check-label"><input name="workflow.follow_eclosion" type="checkbox" defaultChecked={value?.follow_eclosion ?? true}/>{t('workflow.followEclosion')}</label>
    </>}
    {(purpose === 'larvae' || (purpose === 'cross' && goal === 'third_instar')) && <>
      <div className="form-grid">
        <Field label={t('workflow.thirdInstarDay')}><input name="workflow.third_instar_day" type="number" required min={1} max={90} defaultValue={value?.third_instar_day ?? 5}/></Field>
        <Field label={t('workflow.thirdInstarStart')}><input name="workflow.third_instar_start" type="time" required defaultValue={value?.third_instar_window?.[0] || '09:00'}/></Field>
        <Field label={t('workflow.thirdInstarEnd')}><input name="workflow.third_instar_end" type="time" required defaultValue={value?.third_instar_window?.[1] || '17:00'}/></Field>
      </div>
    </>}
  </section>;
}

export function workflowFrom(form: FormData, goal: Workflow['cross_goal'], base?: Workflow | null): Workflow {
  const str = (key: string, fallback: string) => {const value = form.get('workflow.' + key); return typeof value === 'string' ? value : fallback;};
  return {cross_goal: goal, transfer_enabled: form.get('workflow.transfer_enabled') === 'on',
    remove_day: Number(str('remove_day', String(base?.remove_day || 5))),
    selection_day: Number(str('selection_day', String(base?.selection_day || 10))), selection_days: Number(str('selection_days', String(base?.selection_days || 1))),
    selection_window: [str('selection_start', base?.selection_window[0] || '09:00'), str('selection_end', base?.selection_window[1] || '17:00')],
    third_instar_day: Number(str('third_instar_day', String(base?.third_instar_day ?? 5))),
    third_instar_window: [str('third_instar_start', base?.third_instar_window?.[0] || '09:00'), str('third_instar_end', base?.third_instar_window?.[1] || '17:00')],
    target_genotype: str('target_genotype', base?.target_genotype || ''), selection_notes: str('selection_notes', base?.selection_notes || ''),
    female_virgins: str('female_virgins', base?.female_virgins || 'unconfirmed') as Workflow['female_virgins'],
    follow_eclosion: goal === 'score' ? form.get('workflow.follow_eclosion') === 'on' : base?.follow_eclosion ?? true};
}
