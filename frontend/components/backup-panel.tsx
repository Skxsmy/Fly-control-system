'use client';
import {useEffect, useRef, useState} from 'react';
import {Download, Upload, CheckCircle2} from 'lucide-react';
import {Button} from './ui/button';
import {Field, Modal} from './fly-forms';
import {api} from '@/lib/api';
import {fmtNumber, t} from '@/lib/i18n';

type WorkspaceSummary = {counts: Record<string, number>; timezone: string};
type ImportPreview = {token: string; expires_at: string; incoming: WorkspaceSummary; current: WorkspaceSummary; current_fingerprint: string};
export type RestoreResult = {restored: boolean; counts: Record<string, number>; backup: string};
const MAX_IMPORT_BYTES = 64 * 1024 * 1024;
const countKeys = ['containers', 'egg_batches', 'events', 'logs', 'temperatures', 'availability', 'plans'];

export function BackupPanel({restored}: {restored: (result: RestoreResult) => Promise<void>}) {
  const [importing, setImporting] = useState(false);
  const [result, setResult] = useState<RestoreResult | null>(null);
  return <section className="panel backup-panel">
    <h2>{t('backup.title')}</h2>
    <p className="section-help">{t('backup.description')}</p>
    <div className="backup-actions">
      <a className="button-link" href="/api/backup" download><Download size={16}/>{t('settings.download')}</a>
      <Button variant="outline" onClick={() => setImporting(true)}><Upload size={16}/>{t('backup.import')}</Button>
    </div>
    <p className="section-help">{t('backup.connectionScope')}</p>
    {result && <output className="backup-result"><CheckCircle2 size={18}/><div><strong>{t('backup.restored')}</strong><p>{t('backup.recoveryFile', {filename: result.backup})}</p><a href={`/api/import/recovery/${encodeURIComponent(result.backup)}`} download>{t('backup.downloadRecovery')}</a></div></output>}
    {importing && <ImportBackupDialog close={() => setImporting(false)} restored={async value => {setResult(value); await restored(value); setImporting(false);}}/>}
  </section>;
}

function ImportBackupDialog({close, restored}: {close: () => void; restored: (result: RestoreResult) => Promise<void>}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [confirmation, setConfirmation] = useState('');
  const [busy, setBusy] = useState<'preview' | 'restore' | null>(null);
  const [error, setError] = useState('');
  const upload = useRef<AbortController | null>(null);
  const [completed, setCompleted] = useState<RestoreResult | null>(null);
  useEffect(() => () => upload.current?.abort(), []);
  const dismiss = () => {if (busy !== 'restore') {upload.current?.abort(); close();}};

  async function inspect() {
    if (!file || busy) return;
    if (file.size > MAX_IMPORT_BYTES) {setError(t('error.import_file_too_large')); return;}
    const controller = new AbortController(); upload.current = controller;
    setBusy('preview'); setError(''); setPreview(null); setConfirmation(''); setCompleted(null);
    try {
      const response = await fetch('/api/import/preview', {method:'POST', headers:{'Content-Type':'application/octet-stream'}, body:file, signal:controller.signal});
      const value = await response.json() as ImportPreview & {detail?: unknown};
      if (!response.ok) {const key = typeof value.detail === 'string' ? `error.${value.detail}` : 'error.validation'; throw new Error(t(key) === key ? t('error.generic') : t(key));}
      setPreview(value as ImportPreview);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof TypeError ? t('error.connection') : e instanceof Error ? e.message : t('error.generic'));
    } finally {if (!controller.signal.aborted) setBusy(null);}
  }

  async function restore() {
    if (!preview || confirmation !== 'RESTORE' || busy) return;
    setBusy('restore'); setError('');
    try {
      const value = completed ?? await api<RestoreResult>('/import/restore', 'POST', {token:preview.token, confirmation, expected_current_fingerprint:preview.current_fingerprint});
      setCompleted(value);
      await restored(value);
    } catch (e) {setError(e instanceof Error ? e.message : t('error.generic'));}
    finally {setBusy(null);}
  }

  return <Modal title={t('backup.import')} close={dismiss} wide>
    <p className="section-help">{t('backup.importHelp')}</p>
    <Field label={t('backup.file')} hint={t('backup.fileHelp')}><input type="file" accept=".db,.sqlite,.sqlite3,application/vnd.sqlite3" disabled={!!busy} onChange={e => {upload.current?.abort(); setFile(e.target.files?.[0] ?? null); setPreview(null); setConfirmation(''); setError(''); setCompleted(null);}}/></Field>
    <Button variant="outline" disabled={!file || !!busy} onClick={() => void inspect()}>{t(preview ? 'backup.recheck' : 'backup.preview')}{busy === 'preview' && <span className="spinner"/>}</Button>
    {preview && <>
      <div className="table-scroll import-comparison"><table><caption>{t('backup.comparison')}</caption><thead><tr><th scope="col">{t('backup.records')}</th><th scope="col">{t('backup.current')}</th><th scope="col">{t('backup.selectedFile')}</th></tr></thead><tbody>
        {countKeys.map(key => <tr key={key}><th scope="row">{t(`backup.count.${key}`)}</th><td>{fmtNumber(preview.current.counts[key] || 0)}</td><td>{fmtNumber(preview.incoming.counts[key] || 0)}</td></tr>)}
        <tr><th scope="row">{t('settings.timezone')}</th><td>{preview.current.timezone}</td><td>{preview.incoming.timezone}</td></tr>
      </tbody></table></div>
      <p className="notice warning">{t('backup.replaceWarning')}</p>
      <Field label={t('backup.confirmLabel')}><input value={confirmation} autoComplete="off" disabled={busy === 'restore'} onChange={e => setConfirmation(e.target.value)} placeholder="RESTORE"/></Field>
    </>}
    {error && <p className="error" role="alert">{error}</p>}
    <div className="form-footer"><Button variant="outline" disabled={busy === 'restore'} onClick={dismiss}>{t('common.cancel')}</Button>{preview && <Button variant="destructive" disabled={confirmation !== 'RESTORE' || !!busy} onClick={() => void restore()}>{t(completed ? 'backup.reload' : 'backup.restore')}{busy === 'restore' && <span className="spinner"/>}</Button>}</div>
  </Modal>;
}
