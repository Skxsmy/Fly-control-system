'use client';
import {useCallback, useEffect, useState} from 'react';
import {api} from '@/lib/api';
import {t} from '@/lib/i18n';
import type {Culture} from '@/lib/types';
import {Button} from './ui/button';
import {Field, Form, Modal} from './fly-forms';

type Preview = {label:string; fingerprint:string; can_delete:boolean; counts:Record<string,number>; blockers:{id:string; label:string}[]};
export function DeleteContainerForm({culture, close, deleted}: {culture:Culture; close:()=>void; deleted:()=>Promise<void>}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error,setError] = useState('');
  const refresh = useCallback(async () => {try {setPreview(await api<Preview>(`/containers/${culture.id}/delete-preview`));setError('');} catch (e) {setError((e as Error).message);}}, [culture.id]);
  useEffect(()=>{let current = true; void api<Preview>(`/containers/${culture.id}/delete-preview`).then(value=>{if(current)setPreview(value);}).catch(e=>{if(current)setError((e as Error).message);});return()=>{current=false;};},[culture.id]);
  return <Modal title={t('delete.title')} description={t('delete.hint')} close={close}>
    {error && <p role="alert" className="error">{error}</p>}
    {!preview ? <p>{t('common.loading')}</p> : <>
      <p><strong>{preview.label}</strong></p><ul>{Object.entries(preview.counts).filter(([, count])=>count > 0).map(([key,count])=><li key={key}>{t(`delete.count.${key}`,{count})}</li>)}</ul>
      {!preview.can_delete ? <><p className="notice warning">{t('delete.blocked')}</p><ul>{preview.blockers.map(b=><li key={b.id}>{b.label}</li>)}</ul></> : <Form close={close} label={t('delete.confirm')} submit={async form=>{
        const entry = form.get('confirmation_label');
        await api(`/containers/${culture.id}`, 'DELETE', {confirmation_label: typeof entry === 'string' ? entry : '', fingerprint: preview.fingerprint});
        await deleted();
      }}>
        <p className="notice warning">{t('delete.backup')}</p>
        <Field label={t('delete.typeLabel',{label:preview.label})}><input name="confirmation_label" required autoComplete="off"/></Field>
      </Form>}
    </>}
    <Button variant="ghost" onClick={()=>void refresh()}>{t('delete.refresh')}</Button>
  </Modal>;
}
