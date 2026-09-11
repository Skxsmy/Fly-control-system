# Activity deletion choices

Updated 2026-09-11. All mutation checks used isolated databases.

## Behavior

Independent activities no longer require reverse-chronological deletion. A legacy third-instar collection record followed by a parent transfer can be deleted without changing the transferred parents, destination container, later activity or reminders. Current operations retain automatic undo of their recorded effects when those effects do not conflict with later work.

The deletion dialog also offers **Delete the record, keep current state and later work**. This remains available when automatic undo cannot safely restore an earlier state. It deletes the selected Activity entry and its owning undo history while retaining container state, temperature segments, reminders, linked containers and other Activity entries. It does not claim to reverse a physical operation.

Removing an adult-clear record changes the derived virgin-collection clock; the preview states this consequence. If the selected entry belongs to a grouped operation, companion entries stay and the preview explains that their grouped undo is removed. Deletion requires a fresh preview and saves a backup first.

## Implementation and limits

- Automatic undo checks affected rows and relevant state/clock dependencies. It does not merge different edits within a whole container row.
- The record-only path does not execute undo instructions, even from malformed imported metadata. It removes only the identifiable owning metadata and selected log.
- Deleted-log markers prevent later undo from reintroducing an explicitly deleted Activity. Export/import preserves these markers and unrelated undo history.
- The creation entry remains part of the container; permanent container deletion is its separate operation.

## Verification

- Backend coverage includes independent legacy/current collections, different collection windows, named dependency conflicts, retained linked children, retained physical state, grouped clears, stale previews, malformed metadata, backup failure, deleted-log protection and export/import roundtrips.
- Browser verification removed a legacy collection after a parent transfer, then removed the transfer record through the keep-later choice while retaining its child, source parent state and reminders. Deleting a clear record retained the later 18°C move and changed the clock to **No complete clear recorded**.
- Frontend typecheck, build and changed-file lint passed. See the final validation results in `HANDOFF.md`.
