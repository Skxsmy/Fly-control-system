# Single-day collection, cross workflows, and mistaken-record cleanup

## Correction to the requirement

The user specified one virgin-collection day, default D10, with morning, afternoon, and evening windows. The earlier three-day default was an implementation mistake. It has been removed from generation and editable settings, and `collection_days` accepts only 1. Existing containers/settings are migrated to this count. Reconciliation cancels extra pending generated days and preserves event identity and completed history.

The screenshot showed cancelled tasks across September 20–22. Start/end labels on separate lines obscured the intervals, and cancelled history retained Critical badges. Intervals now appear as `09:00–11:00`, cancellation is named in the history control, and resolved history no longer shows active Critical badges or task actions for closed containers.

## Purpose-specific behavior

New crosses default to F1 selection/scoring, with an explicit alternative for F1 virgin collection. The form records target genotype/phenotype, selection criteria, and whether parental females were verified virgin. Ordinary F1 scoring logs counts/selection in notes and does not label progeny as virgins. Its schedule may follow observed first eclosion; virgin collection stays on the one configured culture day. Stock, virgin production, timed eggs, and hourly Petri-dish experiments have distinct reminders and form controls.

Parent handling includes optional D3 transfer and an editable D3–D5 removal window, omitted once parents have left. This allows removal on an available day without moving the offspring D0. Existing protocols remain until an explicit workflow upgrade; obsolete manually pinned rules are preserved as custom instructions on that switch. Editing selection notes does not duplicate a pinned event.

The directly verified [University of Michigan laboratory protocol](https://bridgeslab.sph.umich.edu/protocols/index.php/Performing_Drosophila_Crosses) separates parental setup/transfer, first F1 eclosion, and sorting/counting offspring by phenotype. Its timings are examples, not universal requirements. The prior PMC source encountered an access challenge. Its genuine paper is available from the [Cambridge institutional repository](https://api.repository.cam.ac.uk/server/api/core/bitstreams/8627fe21-3f65-49ff-b2dc-c399684dfb94/content), DOI 10.1016/j.xpro.2023.102585; it does not justify adding collection days.

## Cleanup

Permanent deletion has an exact-label confirmation, current preview fingerprint, downstream-reference protection, and a mandatory full SQLite backup. Only the chosen container and its owned records are removed. Labels are reused from the lowest available number while internal identities remain new. End culture/Discard continue to preserve history. No user containers were permanently deleted during implementation.

## Verification

The complete backend suite passes **113 tests**. Eleven frontend tests, TypeScript checking, application component/lib lint, and local builds also pass. Tests now isolate import-time database initialization before fixtures run; this prevents personal-database migrations during pytest imports.

Browser QA created a cross with F1 scoring and a virgin-production culture at D10. The cross showed F1 selection rather than virgin collection. The virgin culture showed exactly September 11 at 09:00–11:00, 15:00–15:30, and 19:00–21:00. Advancing the isolated clock to September 12 kept those three September 11 tasks and generated no September 12 collection tasks. The permanent-delete preview displayed the correct record counts, backup explanation, and exact-label field. API tests exercised the actual deletion, backup integrity, rollback, label reuse, and blocked descendant cases in temporary databases.

Historical review documents describe earlier versions; this correction supersedes their three-day collection behavior.
