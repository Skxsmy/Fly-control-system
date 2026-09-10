# Egg-laying selection review

Reviewed September 10, 2026. All test records and simulated clocks used isolated databases.

## Result

Egg-laying containers hold a single known adult genotype and an exact planned or actual start. Linked creation records whether selected adults are parents or offspring, without assuming a complete source transfer. The source's adults and pending work remain unchanged.

## Verification

- Backend: 128 tests passed, including subset selection, required genotype/time, source lineage, legacy migration, and planned activation.
- Frontend: 11 tests passed; TypeScript, lint for changed components, and local production build passed.
- Browser: creating a selected-parent container preserved source parents, transfer count, transfer reminder, and removal reminder.
- Browser: actual start entered as 09:15 was stored and displayed as 09:15 with elapsed hours. This caught and fixed a stale controlled time-field value.
- Browser: an offspring experiment planned for September 22 at 11:20 remained planned after advancing the isolated clock from September 12 to September 23. Egg collection remained disabled.
- Browser: recording actual start on September 23 at 13:35 enabled collection and removed pending setup/source checks. A batch retained its separate 13:35–17:35 laying window and generated a 17:35 collection reminder.
- Browser: standalone egg-container creation accepted one known genotype and a required 12:40 start time. Cross offspring/parent selection switches cleared the previous selected genotype.
- Backend: planned temperature inheritance resolves source history at actual start, including backdated operations; explicit destination temperatures remain unchanged.
- Backend: date-only source forecasts do not claim an exact eclosion hour. The check uses the source's first configured collection window; observed eclosion cancels pending checks without deleting completed history.
- Migration: matching legacy parental strings populate the known genotype; ambiguous strings and missing start times require review. Existing facts remain intact and migration is idempotent.

The local application was backed up and restarted. Read-only comparison verified that personal containers and existing activity, reminders, egg batches, availability, and settings were preserved.

## Limits

Eclosion forecasts remain approximate culture-level estimates. They do not establish the selected adults' genotype or suitability for egg laying. The researcher selects adults and records actual operations. Multiple-source lineage and numerical allocation are not modeled; notes can record quantities and selection details.
