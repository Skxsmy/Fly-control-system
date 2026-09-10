# Flykeeper user-flow and time-simulation review

Review date: 2026-09-09. English UI, single user, local storage, in-app reminders.

## Scope and isolation

Reviewed container creation, existing-culture initial states, D0 arithmetic, early parental transfer, temperature history, independent collection windows, manual reminder changes, personal availability, planning, archive behavior, and backup integrity.

Browser input used isolated databases in `.qa/`, never the user's `data/flykeeper.db`. Automated tests used temporary SQLite databases and injected laboratory clocks. Interactive tests used `backend.review_server` on port 8001 and advanced `.qa/clock.txt`. No operating-system time changes, external notifications, or cloud writes were involved.

## Confirmed findings and repairs

| Priority | Reproduction / previous behavior | Implemented correction |
| --- | --- | --- |
| P1 | Change a 3-day collection protocol to 1 day and back; removed days remain cancelled. | Reactivate automatically removed rules when restored, preserving manual times and IDs. |
| P1 | Complete the morning collection, then remove the morning slot from the template; its completed status consumes the afternoon slot. | Identify collection rules by their window times, with migration for old positional keys. |
| P1 | Send a timestamp with a UTC offset to the local-time API; later calculations mix aware and naive datetimes. | Reject offset timestamps at input validation. |
| P1 | At 15:00, an uncompleted 09:00–11:00 task remains ordinary today's work until midnight. | Move expired windows into Needs attention immediately; retain dates on overdue rows. |
| P2 | Existing-culture creation always starts with parents present, no stage, and transfer count zero. | Add Initial state controls for status, parents, stage, and previous transfers. Retain D0 and optional time. |
| P2 | Use Add tissue from culture details; activity is logged but the bottle reminder remains pending. | Direct operations complete their matching pending reminder. Direct collections match only their actual window. |
| P2 | Disable critical reminders, then request cooling; removed obligations still constrain the plan. | Exclude completed, skipped, disabled, and cancelled rules from the search. |
| P2 | Transfer through the API without explicitly supplying a temperature policy; a forbidden culture becomes allowed. | Inherit the source policy and protocol when unspecified. |
| P2 | Rename B02 to ` B01 ` when B01 exists; surrounding spaces bypass uniqueness. | Normalize the label before checking uniqueness. |
| P2 | Set an extremely small positive 18°C rate; forecasting can overflow. | Bound the editable rate to 0.01–0.99, matching the form. |
| P2 | Create a custom reminder spanning a weekend into an available Monday; only its first date is checked/displayed. | Check availability across all spanned dates and display multi-day tasks throughout their interval. |
| P2 | Add a pending reminder to an archived culture. | Reject the operation and disable its Add control. |
| P2 | Request setup planning for an already feasible 16:00 setup; the original time is unnecessarily replaced with 09:00. | Preserve the requested feasible slot as the zero-intervention first choice. |

## Browser evidence

- Entered a bottle with Unicode genotype/notes and literal `<script>` text. Text remains visible as text.
- Imported `QA-Imported-α` with D0 September 15, no setup time, parents removed, pupae observed, and two prior transfers. At September 21 it showed D6, the correct observations/count, and disabled parent transfer/removal. The tissue operation removed its pending D6 task.
- Created `QA-Fresh` on September 21 at 09:00. It showed D0 and zero equivalent days.
- Advanced to September 23. The cultures showed D2 and D8. A real form submission transferred parents to `QA-Transfer-1`, which showed its own D0 and count 1/2. The source retained D2, count 0/2, and parents transferred.
- Cooled the source on September 23, advanced to September 25: D4 and 3 equivalent days at 25°C. Recorded its actual return to 25°C without resetting its age.
- At the imported bottle's D10, all three windows were separate tasks. Advanced to 15:00 with the morning task unfinished; reproduced and then verified the same-day Needs attention repair.
- Recorded the afternoon collection with complete adult clearing; the clock changed to last clear 15:00, deadline 23:00, while the unfinished morning task remained independent.
- Kept the page open and advanced the clock to 19:00. The next operation form picked up 19:00 through normal refresh behavior. Recording an evening collection without clearing preserved the 15:00 clear and 23:00 deadline.
- Advanced to September 26 at 09:00. The clock showed elapsed; the prior morning's missed work remained in Needs attention.
- Added a September 25–28 custom task through the form. It appeared on September 26 in both Today and Calendar. Changed that Saturday to partial availability 09:00–12:00; morning collection and transfer conflicts cleared, while afternoon/evening collection conflicts remained.

## Automated verification

- Backend: 48 passing tests, including controlled D0 → D2 → D6 → D10 → next-day journeys, all three collection operations, cold/warm integration, partial availability, initial-state variants and invalid inputs, explicit planned activation, protocol restoration and legacy-key migration, transfer limits, atomic operation rollback, and a readable backup with SQLite integrity check.
- Frontend time classification: 3 passing Node tests covering same-day expiry, midnight rollover, and multi-day reminder visibility.
- TypeScript typecheck and local production build pass.
- Lint passes for the application components and `lib` directory. The full scaffold lint still reports 19 existing errors in shared UI components/hooks (accessibility rules, compiler rules, and chart interpolation). These are not presented as a clean full-repository lint run.

## Limits

This validates application behavior under simulated clocks, not the biological accuracy of predicted development. The editable 18°C rate remains an approximation. Stage observations do not calibrate developmental forecasts, and collection timing does not establish virginity.

The time-simulation runner is a development tool, excluded from the normal launcher. The user-facing application continues to use the configured laboratory time zone and has no background notification requirement.

The browser walkthrough samples real form interactions; it is not an exhaustive browser/device compatibility or accessibility audit. The automatic test suite can be rerun from README commands.
