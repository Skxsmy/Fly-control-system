import {Clock3} from 'lucide-react';
import type {Culture} from '../lib/types';
import {fmtDate, fmtNumber, fmtTime, t} from '../lib/i18n';
import {collectionClockAt} from '../lib/collection-guidance';

export function VirginCollectionGuidance({culture, now, actionTime, compact = false}: {culture: Culture; now: string; actionTime?: string; compact?: boolean}) {
  const clock = collectionClockAt(culture, actionTime ?? now);
  return <section className={`clock-panel ${clock.state !== 'within' ? 'warning' : ''}`} aria-label={t('clock.title')}>
    <h3><Clock3 size={17}/>{t('clock.title')}</h3>
    <p>{t('collectionGuidance.windows', {windows: culture.template.windows.length})}</p>
    <p><strong>{t(`clock.${clock.state}`)}</strong></p>
    {actionTime !== undefined && <small>{t('collectionGuidance.actionTime')}</small>}
    {clock.last_clear && <small>{t('clock.last')}: {fmtDate(clock.last_clear)} · {fmtTime(clock.last_clear)}</small>}
    {clock.deadline && <small>{t('clock.deadline')}: {fmtDate(clock.deadline)} · {fmtTime(clock.deadline)}</small>}
    {clock.state !== 'within' && <p>{t(`collectionGuidance.${clock.state}`)}</p>}
    <small>{t('collectionGuidance.protocol', {hours: fmtNumber(clock.protocolHours), temperature: clock.temperature})}</small>
    {!compact && <p>{t('collectionGuidance.clear')}</p>}
    <small>{t('collectionGuidance.verify')}</small>
  </section>;
}
