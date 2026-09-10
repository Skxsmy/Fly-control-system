# Flykeeper

A single-user, local-first Drosophila culture manager. The interface, documentation, and internal identifiers are in English. Translation packs can be added without changing saved biological records.

## Start the app

Double-click **Start-Flykeeper.cmd**. The default address is [Flykeeper](http://127.0.0.1:48173). If that port is occupied, the launcher tries the next 20 ports and opens the actual address. Change the preferred port in `flykeeper.config.json`; restarting applies the change. Repeat launches reuse this workspace's existing instance.

For a hidden server process, use **Start-Flykeeper-Background.cmd**. It opens the browser and stores server diagnostics in `.runtime/server.log`. To stop the server from outside the browser, double-click **Stop-Flykeeper.cmd**. Alternatively use **Protocols & settings → Shut down Flykeeper**. These request graceful shutdown of this workspace's managed instance, without terminating unrelated Python processes or other listeners. Closing a browser tab alone leaves the server running. No background notifications are scheduled.

The actual port and instance metadata are kept in `.runtime/server.json`; this file contains a local shutdown token and is excluded from version control.

For a fresh installation, install Python 3.13+ and Node.js 22.13+, then run `Setup-Flykeeper.ps1` in PowerShell.

## First workflow

1. Open **Protocols & settings**. Set the laboratory time zone and weekly availability before recording cultures. Date-specific overrides are edited in **Calendar**.
2. Choose **New container**. Choose vial, bottle, Petri dish, or egg-laying container. Enter purpose, genotype(s), and setup date. Time is optional for ordinary fly cultures and required for Petri dishes. Each record has a unique human-readable ID.
3. Open a container to transfer parents, establish a new generation, record observations, collect females, clear adults, or record an actual temperature move.
4. Use **Today** for pending and overdue work. Each collection window is a separate task. Completion, skip, disable, reschedule, and restore are available per reminder.
5. For a planned culture, **Find a setup date** suggests available starts. For an active cross, **Find a cooling plan** searches for an approximate minimal cold interval.

The workspace starts empty. Tests use a separate temporary database; no demonstration cultures are inserted into your records.

## Implemented rules

- Setup date is **D0**. Each new vial/bottle has an independent timeline. A date-only setup remains date-only in storage and is visibly marked approximate.
- Same-parent transfers increment the cohort's transfer index in the destination. Source records preserve their historical index and continue developing. Defaults: calendar D3, maximum two transfers. Early transfers use the actual new setup as the next interval anchor.
- **Start next generation** creates a new cohort at transfer index zero. It does not pretend that offspring are the old parents.
- Development checks default to equivalent D6; bottles receive a tissue task. This is a lab-defined inspection rule, not a claim that larvae first appear on D6.
- Cross/virgin templates default to an eclosion watch at equivalent D9, followed by three collection windows per day beginning equivalent D10 for three days. D11 and other values are configurable.
- Stock templates have a separately configurable renewal interval (initially 11 calendar days), without automatic virgin collection tasks.
- Physical status, original-parent presence, observed stage, and temperature are stored separately. Forecasts do not overwrite observations.
- **Initial state** supports importing existing cultures: choose active/planned status, parent presence, observed stage, and previous parent transfer count. Preserve the original setup date. Temperature at setup is the historical starting temperature; record later temperature moves separately. Imported stages do not fabricate a clear time or reset D0.
- Actual temperature history affects developmental forecasts. D3 parent transfer and stock-renewal intervals remain calendar based.
- A complete adult clear starts the collection clock. Merely recording a collection does not. Default protocol thresholds are 8 h at 25°C and 16 h at 18°C; mixed-temperature intervals are marked for manual assessment, not linearly converted.
- Manual rescheduling pins the reminder. Forecast recalculation preserves pinned, completed, skipped, and disabled work. Restore deliberately returns an eligible generated task to its template.
- Ending/discarding a culture cancels pending tasks but preserves records and activity.
- A missed collection window appears in **Needs attention** as soon as its end time passes, including on the same day. Multi-day custom reminders appear on each applicable calendar day.

## Egg-laying and hourly experiments

1. Create an **Egg-laying container** with the female and male genotypes. This record holds the parents and can produce multiple egg collections. It does not inherit vial D3/D6/D10 reminders.
2. Open **New egg collection**. Give the batch a label, expected or verified egg genotype, temperature, and laying start/end timestamps. A collection reminder is created for the end of the window. A parental cross description is retained as text and is not interpreted as a genetic prediction.
3. After the laying window has ended, use **Record egg collection** with the actual pickup time. The laying interval and collection time are separate facts.
4. Use **Prepare Petri dish** for an aliquot. The dish retains the source batch and its laying interval. Multiple dishes can share a source batch; setting up a dish does not reset egg age. External eggs can instead be entered manually in a new Petri dish.
5. For direct imaging, choose **Record egg use** on the batch. This does not require a dish and does not consume/close other aliquots. **Add reminder** can schedule imaging or another use. Quantities and allocation details are recorded in notes, not enforced as an inventory balance.
6. The Petri dish displays an egg-age range in hours and an expected first-instar window. The editable default is 24–30 hours, a planning preset rather than a validated universal range. Earliest time = laying start + minimum age; latest time = laying end + maximum age. For eggs laid September 10, 09:00–13:00, this preset gives September 11, 09:00–19:00.
7. Record **Observe first instar** after inspection. Dissection and imaging can be logged separately, and their reminders can be manually scheduled. The predicted hatch interval is not a guarantee that all larvae remain first instar throughout that interval.

### Start egg laying from an existing vial or bottle

Open an active vial/bottle and choose **Create egg-laying container** under **Linked egg-laying containers**. Select which adults you are using:

- **Move all original parents** retains their cohort and increments the transfer count. It requires parents to be present and below the source protocol's transfer limit. Saving records them as transferred and completes a pending parent-transfer reminder. Developing offspring and other source reminders keep their existing timeline.
- **Select offspring from this culture** starts a new cohort with transfer count zero. Source parent state and reminders are preserved. If you completely clear the source, record that separately.

Stock/virgin genotype text is prefilled for both sexes; verify the selected flies. A parental cross is copied when moving its original parents. When selecting cross offspring, enter their actual genotypes; the app does not infer Mendelian outcomes. Genotypes and notes can be edited for the new record without changing the source. The temperature policy and protocol defaults are inherited; the default setup temperature follows the source's recorded temperature at the new setup time, with an explicit override available.

The new record has an independent D0, no copied observations, temperature history, egg batches, or vial-cycle reminders. Actual setup must be between source setup and now. The source and destination link to each other; the destination records whether its adults were original parents or selected offspring. Continue with **New egg collection**, then Petri dishes or direct egg use as above. Partial transfers of original parents and combining adults from multiple source containers are not yet modeled by this shortcut.

The [JoVE timed-collection protocol](https://www.jove.com/v/20076/drosophila-burrowing-tunneling-assay-method-to-assess-tissue-hypoxia) describes a four-hour laying period and incubation at 25°C, with most larvae hatched by the following afternoon. Its video summary also describes a 24-hour incubation after timed collection. The software's 24–30-hour preset combines a practical starting estimate with the researcher's requested approximate 30-hour timing; it is not a measured confidence interval from that publication. Genotype, culture conditions, and the width of the laying window require local calibration.

Choose the reference temperature for the entered hour bounds. If recorded laying/incubation temperatures differ, the dish and its task display a review warning. This workflow does not apply the culture manager's approximate 18°C multiplier or automatic cooling planner to an hour-sensitive experiment. Manually rescheduling a task changes the work plan, while the biological estimate remains visible separately.

## Moving reminders

**Reschedule** updates the existing event ID and pins its time. By default **Keep duration when moving** moves both ends of its interval. Turn this off to set a separate end. A time-point task can have identical start/end times. An intentionally multi-day interval appears on every date it spans.

Previously saved spanning events are preserved; they are not silently shortened. If an existing reminder accidentally spans two days, reschedule it with **Keep duration** off and correct its end, or restore the template before moving it. A new template day or another collection slot is a separate task and is not moved by editing a single reminder.

## Planning model and limits

The development model accumulates `elapsed days × rate`. The initial rates are 1.0 at 25°C and 0.5 at 18°C; the latter is editable. For date-only setups, midnight is an internal lower-bound reference, not a fabricated observed setup time. Predictions are approximate culture-level dates, not synchronized egg ages or confidence intervals.

Planned setup search considers available slots over the next 14 days and prioritizes dates closest to the requested start. An active-culture search considers one cold interval, at hourly handling slots, up to seven cold days. It checks both physical moves and every generated critical window, including eclosion watch and repeated collection. Tasks need a contiguous 15-minute overlap with availability. Recommendations are optimal only among the bounded candidates, not across every possible biological or scheduling strategy.

The planner cannot guarantee eclosion timing or virginity. It does not infer a calibrated uncertainty distribution, model light-cycle effects, automatically interpret genotype temperature sensitivity, or linearly convert adult sexual maturation across mixed temperatures. A forbidden-temperature policy disables cooling recommendations. Manually pinned critical tasks require review before optimization. An already-cold culture or one whose predicted watch has begun requires manual assessment.

Accepting a cooling plan creates handling reminders only. It does not fabricate actual temperature history or silently move the factual calendar to the proposed future. Record each actual move when performed. Observation logging preserves biological facts; it does not invent a stage-to-eclosion calibration.

Automatic setup planning and cooling are included. Flexible rescheduling of other operations is manual, because this first version does not assume biological tolerance ranges for your protocols.

## Data and backup

- `data/flykeeper.db`: SQLite database containing all personal records and settings.
- `backups/`: consistent SQLite snapshots created by **Download backup**.
- The launch window displays startup and runtime diagnostics.

The backup endpoint uses SQLite's online backup API. Restore with the app stopped: preserve your current database separately, replace `data/flykeeper.db` with the downloaded snapshot, and restart. Sync exported snapshots rather than a running database. `FLYKEEPER_DB` can select a different local database path for tests or another isolated workspace.

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
