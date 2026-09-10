import {Clock3} from 'lucide-react';
import type {Culture} from '../lib/types';
import {fmtDate, fmtNumber, fmtTime, t} from '../lib/i18n';
import {collectionClockAt} from '../lib/collection-guidance';

export function VirginCollectionGuidance({culture, now, actionTime}: {culture: Culture; now: string; actionTime?: string; compact?: boolean}) {
  const clock = collectionClockAt(culture, actionTime ?? now);
  return <section className={`clock-panel ${clock.state !== 'within' ? 'warning' : ''}`} aria-label={t('clock.title')}>
    <h3><Clock3 size={17}/>{t('clock.title')}</h3>
    <p><strong>{t(`clock.${clock.state}`)}</strong></p>
    {clock.last_clear && <p>{t('clock.last')}: {fmtDate(clock.last_clear)} · {fmtTime(clock.last_clear)}</p>}
    {clock.deadline && <p>{t('clock.deadline')}: {fmtDate(clock.deadline)} · {fmtTime(clock.deadline)}</p>}
    <p>{t('collectionGuidance.protocol', {hours: fmtNumber(clock.protocolHours), temperature: clock.temperature})}</p>
  </section>;
}
