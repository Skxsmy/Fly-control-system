# Flykeeper

A single-user, local-first Drosophila culture manager. The interface, documentation, and internal identifiers are in English. Translation packs can be added without changing saved biological records.

## Start the app

Double-click **Start-Flykeeper.cmd**. The default address is [Flykeeper](http://127.0.0.1:48173). If that port is occupied, the launcher tries the next 20 ports and opens the actual address. Change the preferred port in `flykeeper.config.json`; restarting applies the change. Repeat launches reuse this workspace's existing instance.

For a hidden server process, use **Start-Flykeeper-Background.cmd**. It opens the browser and stores server diagnostics in `.runtime/server.log`. To stop the server from outside the browser, double-click **Stop-Flykeeper.cmd**. Alternatively use **Protocols & settings → Shut down Flykeeper**. These request graceful shutdown of this workspace's managed instance, without terminating unrelated Python processes or other listeners. Closing a browser tab alone leaves the server running. No background notifications are scheduled.

The actual port and instance metadata are kept in `.runtime/server.json`; this file contains a local shutdown token and is excluded from version control.

For a fresh installation, install Python 3.13+ and Node.js 22.13+, then run `Setup-Flykeeper.ps1` in PowerShell.

## First workflow

1. Open **Protocols & settings**. Set the laboratory time zone and weekly availability before recording cultures. Date-specific overrides are edited in **Calendar**.
2. Choose **New container**. Choose vial, bottle, Petri dish, or egg-laying container. Enter purpose, genotype(s), and setup date. Time is optional for ordinary fly cultures and required for Petri dishes and egg-laying containers. Each record has a unique human-readable ID.
3. Open a container to transfer parents, establish a new generation, record observations, collect females, clear adults, or record an actual temperature move.
4. Use **Today** for pending and overdue work. Each collection window is a separate task. Completion, skip, disable, reschedule, and restore are available per reminder.
5. For a planned culture, **Find a setup date** suggests available starts. For an active cross, **Find a cooling plan** searches for an approximate minimal cold interval.

The workspace starts empty. Tests use a separate temporary database; no demonstration cultures are inserted into your records.

## Implemented rules

- Setup date is **D0**. Each new vial/bottle has an independent timeline. A date-only setup remains date-only in storage and is visibly marked approximate.
- Same-parent transfers increment the cohort's transfer index in the destination. Source records preserve their historical index and continue developing. Defaults: calendar D3, maximum two transfers. Early transfers use the actual new setup as the next interval anchor.
- **Start next generation** creates a new cohort at transfer index zero. It does not pretend that offspring are the old parents.
- Development checks default to equivalent D6; bottles receive a tissue task. This is a lab-defined inspection rule, not a claim that larvae first appear on D6.
- Virgin production and crosses explicitly targeting F1 virgins use an eclosion watch at equivalent D9, followed by **one collection day only**, default equivalent D10, with three independent windows: 09:00–11:00, 15:00–15:30, and 19:00–21:00. The collection day and windows can be edited; no extra collection days are generated. The earlier three-day default was an implementation error, not the user's protocol.
- Stock templates have a separately configurable renewal interval (initially 11 calendar days), without automatic virgin collection tasks.
- Physical status, original-parent presence, observed stage, and temperature are stored separately. Forecasts do not overwrite observations.
- **Initial state** supports importing existing cultures: choose active/planned status, parent presence, observed stage, and previous parent transfer count. Preserve the original setup date. Temperature at setup is the historical starting temperature; record later temperature moves separately. Imported stages do not fabricate a clear time or reset D0.
- Actual temperature history affects developmental forecasts. D3 parent transfer and stock-renewal intervals remain calendar based.
- A complete adult clear starts the collection clock. Merely recording a collection does not. Default protocol thresholds are 8 h at 25°C and 16 h at 18°C; mixed-temperature intervals are marked for manual assessment, not linearly converted.
- Manual rescheduling pins the reminder. Forecast recalculation preserves pinned, completed, skipped, and disabled work. Restore deliberately returns an eligible generated task to its template.
- Ending/discarding a culture cancels pending tasks but preserves records and activity.
- A missed collection window appears in **Needs attention** as soon as its end time passes, including on the same day. Multi-day custom reminders appear on each applicable calendar day.

## Purpose-specific culture workflows

| Purpose | Default reminders and output |
| --- | --- |
| Stock maintenance | Culture/bottle check and stock renewal; optional parent transfer is off by default. |
| Virgin collection | Optional D3 parent transfer, a D3–D5 parent-removal window, D6 culture check, D9 eclosion watch, and the three windows on D10 only. |
| Genetic cross: F1 selection/scoring | Parental handling and development checks, then one default F1 selection/scoring window on D10, 09:00–17:00. No automatic virgin-collection reminders. |
| Genetic cross: F1 virgin collection | Parental handling and development checks, then the same single-day three-window collection schedule, with a recorded target F1 genotype/phenotype. |
| Third-instar larval collection / cross targeting F1 third-instar larvae | Parental handling and one larval collection window on calendar D5, initially 09:00–17:00. |
| Egg-laying container | Exact planned/actual start, source offspring eclosion checks when planned, and independent timed egg collections. |
| Petri dish | Egg-age range and an hour-based first-instar estimate. |

The cross form records parental female virgin status, target F1 genotype/phenotype, and selection criteria. These are researcher-entered facts, not automatically inferred genetic outcomes. **Record F1 selection/scoring** logs phenotypes, sex, and counts in notes without classifying flies as virgin. **Observe eclosion** records the first observed F1 eclosion time and completes an associated watch task. F1 scoring can follow that observed date; virgin collection remains on its configured culture day. The editable parent-removal window ends at 17:00 on default D5, starts on the earlier of the transfer day or removal day, and disappears after parents leave. D0 and offspring development remain unchanged.

The [University of Michigan cross protocol](https://bridgeslab.sph.umich.edu/protocols/index.php/Performing_Drosophila_Crosses) distinguishes parental setup/transfer from observing F1 emergence and sorting/counting progeny by phenotype. Its five-day parental transfer and approximately ten-day emergence timing inform editable starting presets, not universal guarantees. D3 optional transfer, maximum two transfers, and a single D10 virgin-collection day remain the user's lab rules. The previously cited virgin-collection paper is also available as a [Cambridge institutional-repository PDF](https://api.repository.cam.ac.uk/server/api/core/bitstreams/8627fe21-3f65-49ff-b2dc-c399684dfb94/content); it does not justify adding extra collection days.

On upgrade, stored collection-day counts become one. Extra pending automatic collection tasks are cancelled; completed history and event IDs are preserved. Cancelled tasks are hidden unless **Show history** is enabled, and do not display an active Critical badge. Existing containers otherwise retain their workflow until you enable **Use the purpose-specific workflow** in Edit. On an explicit workflow switch, manually pinned tasks whose rules disappear are retained as custom work; unchanged pinned rules are not duplicated.

Collection windows are displayed as a single interval, such as **09:00–11:00**. The collection form evaluates the actual complete-clear clock at the entered operation time, including backdated records, and marks unknown, elapsed, or mixed-temperature intervals for assessment. Scheduled times and clock state do not verify individual virginity; collecting selected females alone does not reset the clock.

## Third-instar larval collection

Choose **Third-instar larval collection** as the purpose of a new vial/bottle, with a single known genotype. For a genetic cross, choose **F1 third-instar larvae** under **Cross outcome** and record the parental genotypes and target F1 criteria.

The provisional default is **D5**, five calendar days after that container's setup date (D0), with one 09:00–17:00 collection window. For example, a September 23 setup produces a September 28 reminder. Edit **Third-instar collection day** and the window, or reschedule the individual reminder. This initial calendar rule does not shift with recorded temperature changes; adjust it for the experiment's actual conditions. A transferred destination has its own D0 and collection date.

These workflows schedule parental handling followed by larval collection, without later D6 inspection, eclosion, scoring, or virgin-collection tasks. **Collect third-instar larvae** records the actual time and notes and completes the corresponding reminder. It is also available as a manual operation on other vials/bottles. It does not imply that all larvae were taken, remove adults, reset development, or end the culture.

## Egg-laying and hourly experiments

1. Create an **Egg-laying container** with one **Known adult genotype** and an exact start date and time. The adults have already been selected; this is not a new genetic cross. The container can produce multiple egg collections and does not inherit vial D3/D6/D10 reminders.
2. Open **New egg collection**. Give the batch a label, expected or verified egg genotype, temperature, and laying start/end timestamps. A collection reminder is created for the end of the window. The known adult genotype is prefilled; record the appropriate egg genotype for the batch.
3. After the laying window has ended, use **Record egg collection** with the actual pickup time. The laying interval and collection time are separate facts.
4. Use **Prepare Petri dish** for an aliquot. The dish retains the source batch and its laying interval. Multiple dishes can share a source batch; setting up a dish does not reset egg age. External eggs can instead be entered manually in a new Petri dish.
5. For direct imaging, choose **Record egg use** on the batch. This does not require a dish and does not consume/close other aliquots. **Add reminder** can schedule imaging or another use. Quantities and allocation details are recorded in notes, not enforced as an inventory balance.
6. The Petri dish displays an egg-age range in hours and an expected first-instar window. The editable default is 24–30 hours, a planning preset rather than a validated universal range. Earliest time = laying start + minimum age; latest time = laying end + maximum age. For eggs laid September 10, 09:00–13:00, this preset gives September 11, 09:00–19:00.
7. Record **Observe first instar** after inspection. Dissection and imaging can be logged separately, and their reminders can be manually scheduled. The predicted hatch interval is not a guarantee that all larvae remain first instar throughout that interval.

### Start egg laying from an existing vial or bottle

Open a vial/bottle and choose **Create egg-laying container** under **Linked egg-laying containers**. Choose **Parents** or **Offspring**. You decide which and how many adults to select. Both options preserve the source's parent status, developing offspring, and pending transfer/removal reminders. Record a complete removal or clear separately if that is what you actually performed.

Parents retain their cohort and increment the selected adults' transfer count in the destination. This selection is not blocked by the ordinary vial transfer limit or the source's recorded parent status. Offspring start a new cohort with transfer count zero. Enter one established adult genotype. Stock/virgin genotype text is prefilled for review; a genetic cross is not converted into an assumed genotype. Notes and temperature policy are copied and remain editable in the new record.

Choose **Started — record actual time** for an operation already performed, or **Planned — start later** to prepare in advance. Date and time are required in both cases. Offspring selection defaults to planning and displays the source's approximate eclosion forecast, including recorded temperature changes, or its first observed eclosion time when available. A planned source can also supply a planned offspring experiment.

A planned egg container has a start reminder and, until source eclosion is observed, a separate source-offspring check. Moving or completing a reminder does not automatically start egg laying. Even when time passes beyond the planned start, the container remains planned. **Record actual start** records the actual placement time and enables **New egg collection**; each batch then has its own laying start/end. The source check follows its forecast unless manually rescheduled. Forecasts are planning estimates and do not establish genotype or adult suitability for egg laying.

The default setup temperature uses the source history at the actual start; an explicit destination temperature overrides inheritance. Each destination has its own exact start and hourly elapsed-time display, without copying source observations, egg batches, or culture-cycle reminders. The source and destination link to each other. Combining adults from multiple source containers is not modeled as multiple lineage links; details can be recorded in notes.

On upgrade, older egg-laying records with matching female/male genotypes receive that single genotype. Ambiguous genotypes and missing start times are flagged for review before new egg batches can be added. Existing parental fields, batches, observations, and source status changes are preserved. Edit the record to supply the known genotype and any missing actual start time; the corrected time must precede recorded activity and laying windows.

The [JoVE timed-collection protocol](https://www.jove.com/v/20076/drosophila-burrowing-tunneling-assay-method-to-assess-tissue-hypoxia) describes a four-hour laying period and incubation at 25°C, with most larvae hatched by the following afternoon. Its video summary also describes a 24-hour incubation after timed collection. The software's 24–30-hour preset combines a practical starting estimate with the researcher's requested approximate 30-hour timing; it is not a measured confidence interval from that publication. Genotype, culture conditions, and the width of the laying window require local calibration.

Choose the reference temperature for the entered hour bounds. If recorded laying/incubation temperatures differ, the dish and its task display a review warning. This workflow does not apply the culture manager's approximate 18°C multiplier or automatic cooling planner to an hour-sensitive experiment. Manually rescheduling a task changes the work plan, while the biological estimate remains visible separately.

## Moving reminders

**Reschedule** updates the existing event ID and pins its time. By default **Keep duration when moving** moves both ends of its interval. Turn this off to set a separate end. A time-point task can have identical start/end times. An intentionally multi-day interval appears on every date it spans.

Previously saved spanning events are preserved; they are not silently shortened. If an existing reminder accidentally spans two days, reschedule it with **Keep duration** off and correct its end, or restore the template before moving it. A new template day or another collection slot is a separate task and is not moved by editing a single reminder.

## Planning model and limits

The development model accumulates `elapsed days × rate`. The initial rates are 1.0 at 25°C and 0.5 at 18°C; the latter is editable. For date-only setups, midnight is an internal lower-bound reference, not a fabricated observed setup time. Predictions are approximate culture-level dates, not synchronized egg ages or confidence intervals.

Planned setup search considers available slots over the next 14 days and prioritizes dates closest to the requested start. An active-culture search considers one cold interval, at hourly handling slots, up to seven cold days. It checks both physical moves and every generated critical window, including parental removal, eclosion watch, and the selected collection/scoring workflow. Tasks need a contiguous 15-minute overlap with availability. Recommendations are optimal only among the bounded candidates, not across every possible biological or scheduling strategy.

The planner cannot guarantee eclosion timing or virginity. It does not infer a calibrated uncertainty distribution, model light-cycle effects, automatically interpret genotype temperature sensitivity, or linearly convert adult sexual maturation across mixed temperatures. A forbidden-temperature policy disables cooling recommendations. Manually pinned critical tasks require review before optimization. An already-cold culture or one whose predicted watch has begun requires manual assessment.

Accepting a cooling plan creates handling reminders only. It does not fabricate actual temperature history or silently move the factual calendar to the proposed future. Record each actual move when performed. Observation logging preserves biological facts; it does not invent a stage-to-eclosion calibration.

Automatic setup planning and cooling are included. Flexible rescheduling of other operations is manual, because this first version does not assume biological tolerance ranges for your protocols.

The [experiment planner design proposal](docs/experiment-planner-design.md) describes researcher-authored L1/L3 workflows, backward scheduling across containers, and optional AI with switchable cloud/local connections. These are planned additions, not implemented features. Transgenesis remains deferred until the researcher defines its workflow.

The standalone [assistant interaction prototype](docs/assistant-design.html) demonstrates editing an experiment and its attached assistant panel. Open it in a browser; it uses fictional examples and keeps edits in memory only. It does not connect a model or change laboratory records. See the [interaction design](docs/assistant-interaction-design.md) for the walkthrough and implementation boundaries.

## Data and backup

- `data/flykeeper.db`: SQLite database containing all personal records and settings.
- `backups/`: consistent SQLite snapshots created by **Download backup**.
- The launch window displays startup and runtime diagnostics.

The backup endpoint uses SQLite's online backup API. Restore with the app stopped: preserve your current database separately, replace `data/flykeeper.db` with the downloaded snapshot, and restart. Sync exported snapshots rather than a running database. `FLYKEEPER_DB` can select a different local database path for tests or another isolated workspace.

To clean up a mistaken/test container, open it and choose **Delete container permanently**. The preview lists its own reminders, logs, temperatures, plans, and egg batches; enter its exact label to confirm. A full SQLite backup is required and saved in `backups/` before deletion. Failure to back up leaves records untouched. Deletion is blocked while other containers or independently attached batch reminders depend on it; review downstream records first. A changed preview must be refreshed. This operation differs from End culture/Discard, which retain history and reserve labels. Permanent deletion releases the label; automatic naming chooses the lowest unused number for each container prefix and assigns a fresh internal identity. Existing containers are never renumbered. Restore from the full backup with the app stopped if necessary.

## Architecture

```text
English React / TypeScript interface
                ↓ same-origin /api
Python FastAPI — validation and atomic operations
                ↓
SQLite — containers, temperature intervals, activity, reminders,
         availability, settings, and proposed plans
```

The generated Sites frontend scaffold and lockfile are retained. The local distribution uses `vite.local.config.ts` to build static React assets, which FastAPI serves at the same loopback address. It does not require a Cloudflare runtime, hosted persistence, or network access during ordinary use. Fonts are system-local.

Developer commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 48173 --reload
# In a second terminal:
cd frontend
npm.cmd run dev:local
```

Validation:

```powershell
.\.venv\Scripts\python.exe -m pytest backend -q
cd frontend
npm.cmd run typecheck
npm.cmd run build:local
node --experimental-strip-types --test lib/*.test.mjs
```

For interactive time simulation, run `.\.venv\Scripts\python.exe -m backend.review_server` from the project root and open `http://127.0.0.1:8001/`. This dedicated runner always uses `.qa/time-review.db`, separate from your workspace. Edit `.qa/clock.txt` with a laboratory-local timestamp such as `2026-09-25T15:00`. The UI picks it up on refresh or its next minute tick. The operating system clock and production server are unaffected. Do not use the QA workspace for real experimental records.

Pytest also uses an isolated import-time bootstrap database via `backend/conftest.py`, before per-test fixtures select temporary databases. This prevents import-time schema upgrades from touching personal records during tests.

See [REVIEW_REPORT.md](REVIEW_REPORT.md) for the user-flow review, fixes, and verification limits.

The local API rejects non-loopback host names and foreign origins. There are no user accounts, email integrations, QR codes, or remote notifications.

## Adding a language

1. Add a message dictionary next to `frontend/lib/i18n/en.ts`.
2. Import it in `frontend/lib/i18n/index.ts` and call `registerLocale('zh-CN', zhCN, '简体中文')`.
3. The settings language selector discovers registered packs. Missing keys fall back to English.
4. Dates, weekdays, times, and numbers are formatted with `Intl`; stable database enum values are never translated. User-written genotypes and notes are preserved verbatim.

UI messages use translation keys. API errors use stable codes translated by the client. Future language work should test longer labels, regional number/date formats, and plural forms; the current interpolation helper supports named parameters but does not yet implement ICU plural rules or right-to-left layouts.

A feature-detected read-only WebMCP `list_fly_containers` tool is included for supporting browsers. It is optional and does not affect normal use. Registration was detected in the review browser; cross-browser tool invocation is not part of the current validation.

## Protocol references

- [BDSC-hosted Drosophila Workers Unite! manual](https://bdsc.indiana.edu/pdf/markstein_flymanual2019.pdf): culture handling, developmental timing, and clock-method collection.
- [Sperling & Glover, STAR Protocols (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10520562/): published collection protocol using 8 h at 25°C and 16 h at 18°C under its experimental conditions.
- [Kuntz & Eisen, PLOS Genetics (2014)](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1004293): temperature-dependent embryogenesis; a reason to treat fixed development rates as approximations.
- [SQLite online backup API](https://www.sqlite.org/backup.html): consistent snapshots of a live database.
