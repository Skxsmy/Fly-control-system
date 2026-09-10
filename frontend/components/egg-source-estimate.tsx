import { fmtDate, fmtTime, t } from '@/lib/i18n';
import type { EclosionEstimate } from '@/lib/types';

export function EggSourceEstimate({estimate}: {estimate?: EclosionEstimate | null}) {
  if (!estimate) return <p className="subtle">{t('eggs.noSourceEstimate')}</p>;
  return <section className="clock-panel">
    <h3>{t(estimate.basis === 'observed' ? 'eggs.sourceObserved' : 'eggs.sourceExpected')}</h3>
    <p>{fmtDate(estimate.at)}{!estimate.date_only && ` · ${fmtTime(estimate.at)}`}</p>
    {estimate.source_planned && <p>{t('eggs.sourcePlannedHint')}</p>}
  </section>;
}
