# Reschedule, process control, and egg-workflow review

## Follow-up: egg-laying containers from vials and bottles

The existing application was committed and pushed before this change (checkpoint `fbaddac`). An active vial or bottle now offers **Create egg-laying container**, with explicit original-parent transfer or selected-offspring modes. The source and destination have navigable links. Genotypes, notes, temperature policy, and protocol defaults are inherited where meaningful; cross offspring require entered genotypes. The destination has its own D0 and records its source relationship. Default temperature inheritance uses the source temperature at the entered setup time, including backdated setup.

Original-parent transfer respects presence and the protocol transfer limit, retains cohort identity, increments the count, and completes only a pending parent-transfer task. Selected offspring start a new cohort at count zero and preserve source state/reminders. Validation failures, including duplicate IDs, leave the entire operation unwritten.

Browser review created an existing stock bottle at D10, parents removed, transfer count 2, and observed eclosion. Its new egg-laying container inherited both `w1118` genotypes and notes, while starting at D0/count 0. A cross vial tested both modes: offspring genotype fields stayed blank until entered; switching to original parents copied the parental cross. Saving the transfer produced count 2 from source count 1, preserved the source D2 development tasks, and exposed both source/destination links. These inputs used only `.qa/eggs-review.db`.

Seventeen added backend cases cover inheritance, cross-offspring validation, both container types, historical temperature selection, invalid dates, absent parents, transfer limits, duplicate-label rollback, inactive sources, and the full source → egg-laying container → egg batch → dish chain. Advancing the isolated clock confirms a 21–25 h egg-age range and the expected hatch window. Total: **79 backend tests and 6 frontend tests pass**, plus TypeScript checking, application component/lib lint, and the local build. Existing unused scaffold lint limitations remain as documented below.

Partial original-parent transfers, multi-source mating, and automatic offspring genotype prediction remain outside this shortcut.

## Results

- A single reschedule does not create a second event. The existing event ID is retained across repeated state refreshes.
- The reported B0001 transfer task was inspected read-only: September 11 09:00 through September 12 09:00. This is one spanning interval, so both days display it. The user's saved dates were left unchanged.
- The form now preserves duration by default, handles intermediate blank date input, and recalculates the end at submission. An explicit Keep duration checkbox enables deliberate independent end editing. Browser verification moved a task from September 11 to September 10; the September 11 calendar count became zero.
- Default port changed to 48173. The launcher binds an available port before starting and tries the next 20 ports if needed. A workspace lock prevents duplicate launches. Occupied-port fallback was tested with a separate live socket.
- Foreground launch, duplicate launch, hidden Python process launch, Stop-Flykeeper.cmd's underlying command, and the settings shutdown button were exercised. Both shutdown paths released the listener. Shutdown validates an instance-specific token; no blanket process termination is used.

## Egg workflow

Added Petri dish and Egg-laying container types. Timed collections are independent egg-batch records. Collection time is confirmed separately from the laying interval. Batches support multiple linked dishes, direct imaging/other uses, and batch-associated custom reminders.

Petri dishes require a setup time and an egg-laying interval. An editable incubation protocol gives minimum/maximum hours and a reference temperature. Its expected window is first egg + minimum hours through last egg + maximum hours. Egg age remains tied to the source laying window after transfer. A temperature mismatch is surfaced for manual review, including on pinned tasks; it is not silently converted using the whole-culture rate.

Browser inputs: QA-Egg-Cage, a September 10 09:00–13:00 batch, collection at 14:00, and a linked dish set up at 14:00. At setup the dish showed egg age 1–5 h and a September 11 09:00–19:00 hatch estimate. Direct imaging was then recorded on the same batch while its Petri dish remained linked and active.

Advancing the browser's isolated laboratory clock to September 11 at 10:00 changed the dish's egg-age display to 21–25 h. Recording first-instar observation updated the observed stage and completed its pending reminder. No system-clock changes were used.

Protocol rationale and the distinction between a scheduling preset and biological evidence are documented in README, with a direct JoVE source. The UI and new message keys remain English and use the existing localization interface.

## Verification

62 backend tests and 6 frontend time-window tests pass. TypeScript checking, lint of application components/lib, and the local build pass. The pre-existing full-scaffold lint limitations from the prior review remain outside this change.

Tests use temporary databases or `.qa/eggs-review.db`. Production experimental records were not populated with QA data, shortened, moved, or deleted. Startup adds the egg-batch table without replacing existing data. Process-control smoke tests used the normal workspace but changed no experimental records.

## Deliberate boundaries

- 24–30 h is an editable planning preset, not a validated universal hatch range or an assured dissection window. Microscopic staging remains a separate recorded observation.
- Egg quantities and aliquot amounts use notes; they are not an automatically balanced stock count.
- Rescheduling changes reminders, not factual laying times or historical operations.
- Graceful shutdown is available for instances launched with the supplied launcher. Raw development Uvicorn processes use their own terminal controls.
