# Flykeeper — maintainer and AI handoff

Snapshot: **2026-09-11**. This is a development handoff, not the installation guide. Read [README.md](README.md) for user-facing setup and features, and [AGENTS.md](AGENTS.md) for project conventions. Source code and current tests take precedence over historical review reports.

Flykeeper is in **active development**. Expect bugs and incomplete workflows; do not treat prior test results as proof that a new change works.

## Scope and product constraints

- Single researcher, local-first SQLite workspace; English UI with translation keys. No accounts, QR codes, collaboration, or closed-app notifications.
- Keep useful operational help and destructive-action consequences. Keep engineering explanations, design rationale, and conversation history out of product screens. Do not use UI design skills for this project.
- Deliver complete paths in the main app. A standalone prototype or an unconnected backend is not a working feature.
- Preserve personal records. Tests and demonstrations must use isolated databases, never `data/flykeeper.db`.
- The researcher owns experimental protocols. Do not silently replace timing presets, infer selected genotypes from a cross, or represent planned handling as a recorded physical operation.

## Source map

| Entry | Responsibility |
| --- | --- |
| `launcher.py`, `flykeeper.config.json`, launcher scripts | Managed local instance, port selection, browser launch, graceful shutdown |
| `backend/app.py` | FastAPI routes, validation, SQLite initialization/migrations, atomic mutations and reminder reconciliation |
| `backend/domain.py` | Clocks, purpose templates, event generation, availability, setup/cooling search, incubation estimates |
| `backend/activity_cleanup.py` | Activity preview/undo, change journals, legacy corrections and dependency checks |
| `backend/container_cleanup.py` | Permanent deletion, required backup, dependency checks, reusable display IDs |
| `backend/workspace_restore.py` | Backup validation, preview, atomic replacement and recovery download |
| `backend/ai_assistant.py`, `backend/ai_models.py` | Profiles, protected credentials, context snapshots, read-only chat, model discovery and diagnostics |
| `frontend/components/fly-app.tsx` | Main navigation, Today, container details, calendar and settings integration |
| `frontend/components/*-form.tsx`, `fly-forms.tsx` | Container, operation, egg-laying and deletion dialogs |
| `frontend/components/assistant-page.tsx`, `ai-settings.tsx` | Integrated assistant and connection UI |
| `frontend/lib/types.ts`, `ai-types.ts`, `api.ts` | Client contracts and API access |
| `frontend/lib/i18n/` | English dictionaries and locale registry; missing keys fall back to English |
| `frontend/vite.local.config.ts` | Local Vite server and `dist/local` production bundle |
| `backend/test_*.py`, `frontend/lib/*.test.mjs` | Backend and focused frontend regression tests |

The ordinary distribution is React/TypeScript → same-origin `/api` → FastAPI → SQLite. FastAPI serves `frontend/dist/local`. The retained Sites/Cloudflare scaffold is not required to run this local distribution; use the `:local` npm scripts.

SQLite tables are `containers`, `temperatures`, `logs`, `events`, `availability`, `plans`, `egg_batches`, and `meta`. Several records use JSON payloads. Database initialization runs when `backend.app` is imported and can perform migrations: select a test database **before** importing it. Mutations use transactions with foreign keys enabled. Current `plans` are cooling plans, not general experiments.

Current migration markers in `meta` include `single_day_collection_v1` and `known_egg_adults_v1`. They constrain stored collection-day counts to one and recover a single egg-adult genotype only when unambiguous. Missing genotype/start time is flagged for correction; historical parental fields and source changes remain intact. Reconciliation upgrades old collection keys while preserving event identity/history. Existing cultures keep their legacy workflow unless the user explicitly switches; pinned work whose rule disappears becomes custom work rather than being lost.

To add a locale, place a dictionary beside `frontend/lib/i18n/en.ts`, import it in `index.ts`, and call `registerLocale('zh-CN', zhCN, '简体中文')`. The settings selector discovers registered packs. Keep database enum values and user-entered genotype/notes unchanged. `Intl` formats dates/numbers; the current named-parameter interpolator does not implement ICU plurals or right-to-left layout.

## Run and verify

Use Python 3.13+ and Node.js 22.13+. From the repository root, `Setup-Flykeeper.ps1` creates `.venv`, installs `backend/requirements-lock.txt`, runs `npm.cmd ci`, and builds the local frontend. It relies on the Windows `py` launcher and `npm.cmd`. Reuse the lockfiles; do not casually regenerate them.

Normal use: `Start-Flykeeper.cmd` or `Start-Flykeeper-Background.cmd`. Stop with `Stop-Flykeeper.cmd` or the app's shutdown control. Default port: **48173**, with the next 20 ports as fallback. Repeat launches reuse this workspace's instance. Closing a browser tab does not stop it.

For an isolated API development session in PowerShell:

```powershell
$env:FLYKEEPER_DB = Join-Path $PWD '.qa\development.db'
.\.venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 48191 --reload
```

In a separate terminal:

```powershell
cd frontend
$env:FLYKEEPER_API_URL = 'http://127.0.0.1:48191'
npm.cmd run dev:local
```

Vite uses port 5173 and proxies `/api` to the configured API URL. Its default target is the personal app on 48173, so set the isolated target explicitly for mutation testing.

Validation from the repository root:

```powershell
.\.venv\Scripts\python.exe -m pytest backend -q
.\.venv\Scripts\python.exe -m pytest backend/test_activity_cleanup.py -q
cd frontend
npm.cmd run typecheck
npm.cmd run build:local
node --experimental-strip-types --test lib/*.test.mjs
```

Use targeted `npx.cmd oxlint <changed paths>` as appropriate. Historical full-scaffold lint has unrelated errors; do not report targeted lint as a clean full-repository check. `backend/conftest.py` selects a temporary import-time database before individual test fixtures run.

Time simulation: run `.\.venv\Scripts\python.exe -m backend.review_server` and open port 8001. It always uses `.qa/time-review.db`. Set `.qa/clock.txt` to a laboratory-local timestamp such as `2026-09-25T15:00`, with no UTC offset; refresh or wait for the next UI minute tick. This does not change OS time or the personal app.

Previously recorded validation before this documentation rewrite: **350 backend tests passed, 1 skipped**, plus a later **40-test activity suite passed**. The skip requires Windows file-symlink privileges. These are historical results; no code tests were run for this documentation snapshot.

## Data, credentials and the running account

- `data/flykeeper.db` holds laboratory records and settings. `FLYKEEPER_DB` selects another database. `.qa/` is for isolated test data.
- `backups/` holds consistent SQLite snapshots. Export includes workspace records/settings and undo metadata. Restore replaces rather than merges the workspace, requires a fresh validated preview, and creates a recovery backup first. AI profiles/keys remain separate.
- Default AI settings: `data/.flykeeper.db.ai-settings.json`; `FLYKEEPER_AI_CONFIG` overrides it. Windows keys use the current account's DPAPI. Non-Windows connections can use profile-specific `FLYKEEPER_AI_CLOUD_API_KEY` / `FLYKEEPER_AI_LOCAL_API_KEY`, bound to corresponding `_ENDPOINT` variables.
- `.runtime/server.json` contains instance metadata **and a shutdown token**. Do not dump it in tool output. `.runtime/server.log` contains diagnostics. These files and database/credential directories are ignored by Git.
- Start the persistent app as the **normal desktop Windows user**, including when an agent restarts it. The offline coding sandbox cannot reach cloud providers, and DPAPI credentials belong to the account that encrypted them. A past sandbox launch caused Windows error 10013 despite valid endpoint/key/model settings.
- Preserve credentials if correcting an account mismatch. Do not write plaintext keys to files or logs, request keys in chat, or replace the personal server with an isolated sandbox process. Use managed shutdown instead of terminating unrelated Python listeners.
- After frontend-only changes, rebuilding `build:local` updates served assets; backend changes need a controlled restart. Preserve unsaved user tabs. Sync exported backups rather than a live SQLite file.

## Biological and scheduling invariants

- Setup is **D0**, never D1. Vial/bottle setup time is optional; a date-only setup remains date-only. Egg-laying/dish workflows require exact timing. Physical status, parent presence, observed stage, actual temperature and forecasts are separate.
- Each destination has its own D0. Same-parent transfers increment the destination cohort's transfer index; source offspring keep developing. Defaults: calendar D3, maximum two ordinary transfers. Early actual transfers anchor the next interval. A new generation starts a new cohort with transfer zero. Adult chronological age is otherwise out of scope.
- Virgin production and F1-virgin cross outcomes have **one configured collection day only**, default equivalent D10, with three independent windows: 09:00–11:00, 15:00–15:30, 19:00–21:00. Never reinstate a multi-day default from an old report or biological reference.
- Stock maintenance uses its own renewal interval (initially 11 calendar days), without automatic virgin tasks. F1 selection/scoring is a separate cross outcome; do not label it virgin collection. Genetic targets and verified selected genotypes are separate facts.
- L3 collection uses the researcher's **calendar D5** preset and initially one 09:00–17:00 window. It does not automatically shift with temperature. Collection does not imply all larvae were taken, adults removed, or culture ended.
- D6 inspection and bottle tissue are lab handling reminders, not an assertion that larvae first appear on D6. Forecasted stages never overwrite observations.
- Culture forecasts accumulate elapsed time × rate: initial 25°C = 1.0, editable 18°C = 0.5. Parent transfer and stock renewal remain calendar-based. Hour-sensitive egg experiments do not use this multiplier automatically.
- A **complete adult clear** starts the virgin-collection clock; collection alone does not. Current thresholds are 8 h at 25°C and 16 h at 18°C. Mixed-temperature intervals require assessment, not linear maturity conversion.
- Rescheduling updates and pins the existing event. Reconciliation preserves manual times and completed/skipped/disabled work. Restore deliberately returns an eligible generated task to its template. An expired window becomes overdue at its end, including the same day.
- Accepting cooling recommendations creates reminders only; record actual moves separately. Planned containers remain planned until explicit actual activation, even when their start time becomes overdue.

Setup search considers candidates through the next 14 days. Cooling search considers one cold interval, hourly handling slots and at most seven cold days; tasks need a contiguous 15-minute overlap with availability. Temperature-forbidden cultures, pinned critical work and already-cold/late cultures need explicit handling rather than a fabricated optimum. Neither stage observations nor the current model calibrate genotype sensitivity, light cycles or uncertainty distributions.

### Egg-laying and Petri dishes

An egg-laying container has one known adult genotype. From a vial/bottle, the user selects **Parents** or **Offspring**, without an assumption that all adults move. The source's parent state is unchanged; complete removal/clearing is a separate action. Parent selection retains cohort provenance; offspring selection starts a new cohort. A cross must not supply an assumed selected genotype.

Planned offspring egg-laying containers show a source eclosion forecast/check until observed. Actual placement time starts the container; each egg batch separately records laying start/end and actual pickup time. Batches support multiple Petri dishes or direct uses such as imaging. Quantities are notes, not a conserved aliquot inventory.

Dishes retain the original laying interval. The editable first-instar estimate is laying start + minimum age through laying end + maximum age, initially **24–30 h**. Dish setup does not reset egg age. Temperature mismatch needs review; a hatch estimate does not establish observed stage or dissection suitability.

## Activity undo and permanent deletion

The Activity trash button removes a mistaken recorded operation **and restores its associated effects**. This is distinct from deleting a container or hiding a log.

- New operations journal changed rows in `meta` under `activity_undo:` in the same transaction. The journal covers container state, temperatures, logs, events, plans and egg batches; grouped collection + clear is one operation.
- Preview supplies effects, blockers, required legacy corrections and a fingerprint. Deletion rechecks the fingerprint, validates the projected records, creates a full backup, and atomically reverses the changes/reconciles reminders.
- Never overwrite later edits or activity. Linked child containers block undo; activity deletion does not cascade into them. Imported journals are untrusted data and are shape/scope/record validated. Oversized journals can explicitly make undo unavailable.
- Legacy records may need a user-selected previous stage/parent state or specific completed reminders to reopen. Creation, linked transfers, egg operations, and activation without sufficient history may be blocked. Do not invent missing prior state just to make deletion succeed.
- After activating a planned egg-laying container, undo its activation from the **destination's Activity**. That reversal also removes the corresponding source log. Directly deleting that source log remains blocked because it does not own the activation journal.
- Permanent container deletion has its own preview, dependency/staleness checks, exact-label confirmation and mandatory backup. It releases the human-readable label for reuse but creates a fresh internal identity. End/discard retains history and reserves the label.

## AI capability boundary

Implemented: main-app Assistant; separate cloud/local profiles; OpenAI-compatible Chat Completions; model discovery; selected-model generation test; optional workspace snapshot; all records or selected containers plus source ancestors; optional target date and editable L1/L3 prompts. Context includes related activity, temperatures, reminders, egg batches, cooling plans and availability/settings. Cloud submission includes selected records and notes.

The assistant is **read-only**: no container/event mutation, plan application, browsing, reference retrieval, or protocol verification. Conversation is in memory, not saved on reload. Context/provider changes reset it; a connection revision check prevents another tab silently changing the destination. No local-to-cloud fallback. Oversized workspace context errors instead of silently dropping records; bounded conversation history reports omissions.

`POST /api/ai/models` calls authenticated provider `GET /models` using draft connection settings, without saving them or sending laboratory records. Saved credentials are reused only for the same profile/origin. Listing success is distinct from generation success; unsupported listing retains manual model entry. Keep bounded responses, error redaction and transport diagnostics.

Not implemented: researcher-authored workflow editor, deterministic multi-container backward experiment solver, saved executable L1/L3 experiment plans, built-in reference database/retrieval, or transgenesis workflow. Existing setup-date and minimal-cooling searches are implemented but bounded approximations, not a global biological optimizer. The standalone HTML experiment prototype is a design reference with fictional data, not a live integration.

## References and continuing work

- [AGENTS.md](AGENTS.md): current project conventions.
- [REVIEW_REPORT.md](REVIEW_REPORT.md): original form/time-flow review, fixes and validation limits. Some historical collection-day examples are outdated; the single-day invariant above controls.
- [Egg-laying selection review](docs/egg-laying-selection-review.md): lineage and planned/actual behavior.
- [AI connection review](docs/ai-connection-review.md): sandbox-account failure, model discovery, transport fixes and historical tests.
- [Assistant integration review](docs/assistant-integration-review.md), [interaction design](docs/assistant-interaction-design.md), [UI cleanup review](docs/ui-cleanup-review.md): implemented UI/data paths and review history.
- [Experiment planner proposal](docs/experiment-planner-design.md), [HTML prototype](docs/assistant-design.html): future workflow editing/solver design, not implementation claims.

Historical external references retained from the earlier README are listed below; their availability/content was **not reverified in this documentation-only update**. Research references inform editable presets, not permission to overwrite the researcher's protocol.

- [BDSC-hosted Drosophila Workers Unite! manual](https://bdsc.indiana.edu/pdf/markstein_flymanual2019.pdf): culture handling and collection.
- [Sperling & Glover, STAR Protocols (2023)](https://pmc.ncbi.nlm.nih.gov/articles/PMC10520562/), with a [Cambridge repository copy](https://api.repository.cam.ac.uk/server/api/core/bitstreams/8627fe21-3f65-49ff-b2dc-c399684dfb94/content): collection protocol; does not justify extra collection days.
- [University of Michigan cross protocol](https://bridgeslab.sph.umich.edu/protocols/index.php/Performing_Drosophila_Crosses): parental handling, F1 emergence and scoring.
- [JoVE timed-collection protocol](https://www.jove.com/v/20076/drosophila-burrowing-tunneling-assay-method-to-assess-tissue-hypoxia): egg laying/incubation background. The application's 24–30 h preset is not a measured confidence interval from this publication.
- [Kuntz & Eisen, PLOS Genetics (2014)](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1004293): temperature-dependent embryogenesis.
- [SQLite online backup API](https://www.sqlite.org/backup.html): consistent snapshots of a live database.

Before editing, inspect Git status and preserve unrelated changes. Read the relevant route, domain rule and UI path together. Add meaningful regression coverage for state transitions, undo/restore dependencies, timing or credential boundaries. Test complete paths with isolated data and simulated time where appropriate. Build the main local bundle; report exactly what was checked and what remains unimplemented. Do not append fresh handoff prose to the human README or product UI.
