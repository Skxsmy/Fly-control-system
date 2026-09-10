# Assistant and backup integration review

Date: 2026-09-10

## Delivered paths

- Main navigation → Assistant → Connect a model → AI connection → Save and test → Assistant → Send.
- Container detail → Ask assistant about this container → selected container and source context.
- Protocols & settings → General / Backup & restore / AI connection.
- Backup & restore → Import backup → Check backup → compare current/incoming contents → Restore workspace → Download recovery backup.

These paths use mounted FastAPI routes and the normal application build. The standalone HTML experiment editor is a design reference, not the live assistant.

Useful help was restored for backup scope, replacement consequences, recovery, API fields, local-server setup, initial culture dates, rescheduled reminders, temperature-rate units, and shutdown. Engineering rationale stays in documentation. Visible labels and messages use English translation keys.

## Verification

- Backend: **251 passed, 1 skipped**. The skipped case requires Windows permission to create a file symlink; download path, filename, missing-file, invalid-content, and traversal checks passed separately.
- Frontend: **11 passed** for existing time-passage, collection-clock, and rescheduling behavior.
- TypeScript, targeted lint on changed frontend files, and the local production build passed.
- Native Windows DPAPI storage and redaction were tested with disposable keys. Test requests used local HTTP stubs, not a real provider account.
- Import tests cover invalid SQLite/schema/records, timing and lineage constraints, stale preview detection, expiry, recovery-backup failure, atomic round trips, and idempotent retries. Mounted app routes were tested before the static frontend mount.

Browser checks used a separate database on port 48191 and a local compatible HTTP test server on 48192:

1. The main Assistant entry opened configuration, saved a local endpoint and model, and displayed a successful connection test.
2. A chat request reached the backend and HTTP server; the returned text listed the three fictional containers received. Selected context sent one selected container; disabling workspace context sent none. Changing scope removed prior conversation while preserving the draft.
3. Target date `2026-09-15` survived fast entry and appeared in both the displayed user message and the received HTTP message.
4. Changing a model while the conversation remained open produced a specific stale-connection error. The page loaded the new connection, cleared prior messages, and retained the unsent message without resending it.
5. Cancelling a delayed request returned immediately to an editable draft with a cancellation message. Separate keyed buttons and preventing the cancelling click's default action fixed an accidental resubmission.
6. A provider authentication error appeared in configuration with the entered model retained.
7. A native file chooser uploaded an actual SQLite backup. Preview showed three current containers versus two incoming containers. Restore was disabled until `RESTORE` was entered. Restoring showed success and a recovery download link; the container table immediately displayed two records. AI configuration survived restoration.
8. No browser console errors or warnings were present during the normal configured chat/import flows. The final production AI connection screen was also inspected with a native browser screenshot; the API fields, profile controls, and save/test actions are visible in the main application.

The personal database was not used for mutation tests. A read-only copy of the current personal database was accepted by the import validator. All eight table digests remained identical across the production restart. Health, AI settings, import validation, and the frontend were verified live on port 48173.

## Remaining boundary

The integrated assistant supports real compatible model requests and reads explicitly selected workspace context. No real cloud provider or installed model was exercised without user configuration. Replies are conversation text; the researcher-authored experiment editor, deterministic backward solver, and reviewed plan application remain future work. Transgenesis remains deferred.
