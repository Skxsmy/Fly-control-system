'use client';
import {useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {fmtDate, fmtTime, t} from '@/lib/i18n';
import type {ActivityRecord, Culture} from '@/lib/types';
import {Button} from './ui/button';
import {Field, Form, Modal} from './fly-forms';

type Preview = {
  fingerprint: string; effects: string[]; blockers: string[]; can_delete: boolean;
  corrections: {field: 'parents' | 'stage'; options: string[]}[];
  reminders: {id: string; kind: string; due: string; end: string; title: string}[];
  related_activities: {id: string; action: string; at: string}[];
  dependent_activities?: {id: string; action: string; at: string}[];
  keep_later?: {can_delete: boolean; effects: string[]; blockers: string[]; fingerprint: string};
};

export function DeleteActivityForm({culture, activity, close, saved}: {
  culture: Culture; activity: ActivityRecord; close: () => void; saved: () => Promise<void>;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [mode, setMode] = useState<'undo' | 'keep_later' | null>(null);
  const path = `/containers/${culture.id}/activities/${activity.id}`;
  useEffect(() => {
    let current = true;
    void api<Preview>(`${path}/delete-preview`).then(value => {
      if (current) setPreview(value);
    }).catch(e => {if (current) setError((e as Error).message);});
    return () => {current = false;};
  }, [path, revision]);
  const method = mode ?? (preview?.can_delete ? 'undo' : 'keep_later');
  const canDelete = method === 'undo' ? preview?.can_delete : preview?.keep_later?.can_delete;
  return <Modal title={t('activity.deleteTitle')} description={t('activity.deleteHint')} close={close}>
    <div className="activity-delete-summary"><strong>{t(`action.${activity.action}`)}</strong>
      <p>{culture.label} · {fmtDate(activity.at)} · {fmtTime(activity.at)}</p>
      {activity.notes && <p>{activity.notes}</p>}
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {!preview && !error && <output>{t('common.loading')}</output>}
    {preview && <>
      <fieldset className="activity-reopen"><legend>{t('activity.method')}</legend>
        <label className="check-label"><input type="radio" name="delete_method" value="undo" checked={method === 'undo'} disabled={!preview.can_delete} onChange={() => setMode('undo')}/>{t('activity.undo')}</label>
        <label className="check-label"><input type="radio" name="delete_method" value="keep_later" checked={method === 'keep_later'} disabled={!preview.keep_later?.can_delete} onChange={() => setMode('keep_later')}/>{t('activity.keepLater')}</label>
      </fieldset>
      {(method === 'undo' ? preview.effects : preview.keep_later?.effects || []).map(effect => <p key={effect}>{t(`activity.effect.${effect}`)}</p>)}
      {method === 'undo' && preview.related_activities.some(item => item.id !== activity.id) && <div>
        <p>{t('activity.related')}</p><ul>{preview.related_activities.filter(item => item.id !== activity.id).map(item =>
          <li key={item.id}>{t(`action.${item.action}`)} · {fmtDate(item.at)} · {fmtTime(item.at)}</li>)}</ul>
      </div>}
      {!preview.can_delete && <div className="activity-undo-conflicts"><p>{t('activity.undoUnavailable')}</p>
        {preview.blockers.map(blocker => <p key={blocker}>{t(`activity.blocker.${blocker}`)}</p>)}
        {!!preview.dependent_activities?.length && <ul>{preview.dependent_activities.map(item => <li key={item.id}>{t(`action.${item.action}`)} · {fmtDate(item.at)} · {fmtTime(item.at)}</li>)}</ul>}
      </div>}
      {method === 'keep_later' && preview.keep_later?.blockers.map(blocker => <p className="notice warning" key={blocker}>{t(`activity.blocker.${blocker}`)}</p>)}
      {canDelete && <Form key={`${preview.fingerprint}-${method}`} close={close} label={t(method === 'undo' ? 'activity.delete' : 'activity.deleteRecord')} destructive submit={async form => {
        const corrections = method === 'undo' ? Object.fromEntries(preview.corrections.map(item => [item.field, form.get(item.field)])) : {};
        await api(path, 'DELETE', {fingerprint: method === 'undo' ? preview.fingerprint : preview.keep_later!.fingerprint, mode: method, corrections, reopen_event_ids: method === 'undo' ? form.getAll('reopen_event_ids') : []});
        await saved(); close();
      }}>
        {method === 'undo' && preview.corrections.map(item => <Field key={item.field} label={t(`activity.restore.${item.field}`)} hint={t('activity.restoreHint')}>
          <select name={item.field} required defaultValue=""><option value="" disabled>{t('activity.choose')}</option>
            {item.options.map(option => <option key={option} value={option}>{t(`${item.field === 'stage' ? 'stage' : 'parents'}.${option}`)}</option>)}
          </select>
        </Field>)}
        {method === 'undo' && preview.reminders.length > 0 && <fieldset className="activity-reopen"><legend>{t('activity.reopen')}</legend>
          {preview.reminders.map(event => <label className="check-label" key={event.id}><input type="checkbox" name="reopen_event_ids" value={event.id}/><span>{event.title || t(`task.${event.kind}`)}<small>{fmtDate(event.due)} · {fmtTime(event.due)}–{fmtTime(event.end)}</small></span></label>)}
        </fieldset>}
      </Form>}
    </>}
    {(error || preview) && <Button variant="ghost" onClick={() => {setPreview(null); setMode(null); setError(''); setRevision(value => value + 1);}}>{t('delete.refresh')}</Button>}
  </Modal>;
}
