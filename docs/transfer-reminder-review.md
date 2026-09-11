# Parent transfers and stock renewal

Verified on 2026-09-11 with isolated databases and the main local UI.

## Changes

- **Transfer parents** now defaults to scheduling the next parent transfer in the destination, including stock and legacy containers. Previously the form inherited stock maintenance's disabled transfer setting, so a successfully created destination could have no next-transfer reminder.
- The destination keeps the cohort, increments its transfer count and starts its own setup clock. Its next transfer uses the configured calendar interval from its actual setup date/time. An explicit reminder opt-out is respected, and reaching the maximum transfer count suppresses another transfer.
- Stock reminders have a **Renew** button. Stock container Operations expose **Renew stock culture**. Both open a form with selectable vial/bottle, inherited genotype, actual setup date/time and displayed transfer count **0**.
- Renewal uses the existing generation endpoint. It creates a new cohort, keeps source parent state, and completes the source renewal reminder in the same transaction. Cancellation or validation failure creates nothing and leaves the reminder pending.

## Validation

- Backend suite after the transfer fix: **372 passed, 1 skipped**. The skip requires Windows file-symlink privileges.
- Expanded transfer/renewal suite: **27 passed**, covering both kinds and all source/destination combinations, legacy workflows, early transfer, custom intervals, explicit opt-out, imported counts, simulated time, rescheduling, invalid renewal and renewal undo.
- Frontend typecheck, local build, changed-file lint and **11 frontend tests** passed.
- Browser checks: bottle transfer at Sep 11 13:15 generated Sep 14 13:15; backdated vial transfer at Sep 10 11:20 generated Sep 13 11:20. Advancing the test clock to Sep 15 placed both reminders in Needs attention. Second transfers reached 2/2 with no third-transfer reminder. Vial → bottle and bottle → vial renewals inherited genotype, reset counts to zero and completed the source renewal reminder. Both the Operations and reminder-button renewal paths were exercised.

Existing false workflow settings are not mass-migrated because they can represent intentional opt-outs. A missing historical reminder should be repaired for the verified affected record, preserving unrelated rows and a backup.
