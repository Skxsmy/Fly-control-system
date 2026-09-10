"""Explicit, backed-up removal of a single mistaken container.

Call deletion inside a fresh ``BEGIN IMMEDIATE`` transaction.  No reconciliation
or other writes should happen on that connection first: the separate SQLite
backup reader must see exactly the committed state being removed.  This module
never commits the caller's transaction and never removes a descendant.
"""
import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException


OWNED_TABLES = ("temperatures", "logs", "events", "plans")
LABEL_PREFIXES = {"vial": "V", "bottle": "B", "petri_dish": "P", "egg_laying": "E"}


def next_container_label(db, kind):
    """Use the lowest free standard label, including labels held by other kinds.

    Archived containers still reserve their labels.  The database UNIQUE
    constraint and the caller's write transaction remain the final safeguards.
    Internal container IDs are independent and must always be newly generated.
    """
    prefix = LABEL_PREFIXES[kind]
    labels = {row[0] for row in db.execute("SELECT label FROM containers")}
    number = 1
    while f"{prefix}{number:04}" in labels:
        number += 1
    return f"{prefix}{number:04}"


def _rows(db, statement, values=()):
    cursor = db.execute(statement, values)
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def _deletion_snapshot(db, cid):
    containers = _rows(db, "SELECT * FROM containers ORDER BY id")
    container = next((row for row in containers if row["id"] == cid), None)
    if container is None:
        raise HTTPException(404, "container_not_found")

    owned = {table: _rows(db, f"SELECT * FROM {table} WHERE container_id=? ORDER BY id", (cid,))
             for table in OWNED_TABLES}
    batches = _rows(db, "SELECT * FROM egg_batches ORDER BY id")
    owned["egg_batches"] = [row for row in batches if row["source_id"] == cid]
    batch_ids = {row["id"] for row in owned["egg_batches"]}
    blockers = []

    for row in containers:
        if row["id"] == cid:
            continue
        value = json.loads(row["payload"])
        reasons = []
        if value.get("source_id") == cid:
            reasons.append("source_container")
        if value.get("egg_batch_id") in batch_ids:
            reasons.append("egg_batch")
        if reasons:
            blockers.append({"type": "container", "id": row["id"], "label": row["label"], "reasons": reasons})

    # Normal API-created batch reminders belong to their source container.
    # Protect independently attached reminders too, rather than orphaning them.
    for row in _rows(db, "SELECT * FROM events WHERE container_id IS NULL OR container_id<>? ORDER BY id", (cid,)):
        value = json.loads(row["payload"])
        if value.get("egg_batch_id") in batch_ids:
            blockers.append({"type": "event", "id": row["id"],
                             "label": value.get("title") or value.get("kind", "Reminder"), "reasons": ["egg_batch"]})

    # Defensively preserve imported records with an inconsistent JSON source.
    for row in batches:
        value = json.loads(row["payload"])
        if row["source_id"] != cid and value.get("source_id") == cid:
            blockers.append({"type": "egg_batch", "id": row["id"],
                             "label": value.get("label", row["id"]), "reasons": ["source_container"]})

    return {"version": 1, "container": container, "owned": owned, "blockers": blockers}


def preview_container_deletion(db, cid):
    """Read-only preview of exact owned records and lineage blockers."""
    snapshot = _deletion_snapshot(db, cid)
    fingerprint = hashlib.sha256(json.dumps(snapshot, sort_keys=True, ensure_ascii=False,
                                            separators=(",", ":")).encode("utf-8")).hexdigest()
    return {"id": cid, "label": snapshot["container"]["label"],
            "counts": {"containers": 1, **{table: len(rows) for table, rows in snapshot["owned"].items()}},
            "blockers": snapshot["blockers"], "can_delete": not snapshot["blockers"],
            "fingerprint": fingerprint}


def _backup_before_delete(db, backup_dir):
    database_path = next((row[2] for row in db.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not database_path:
        raise HTTPException(500, "deletion_backup_unavailable")
    destination = None
    created = False
    try:
        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        destination = folder / f"flykeeper-before-delete-{stamp}-{uuid.uuid4().hex[:8]}.db"
        # A separate reader avoids backing up a connection with an active write
        # transaction, which would otherwise wait for that same transaction.
        with destination.open("xb"):
            created = True
        with closing(sqlite3.connect(database_path, timeout=20)) as source:
            with closing(sqlite3.connect(destination)) as target:
                source.backup(target)
                if target.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise sqlite3.DatabaseError("Backup integrity check failed")
        return destination
    except (OSError, sqlite3.Error) as error:
        if destination is not None and created:
            try:
                destination.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(500, "deletion_backup_failed") from error


def delete_container_permanently(db, cid, confirmation_label, fingerprint, backup_dir):
    """Validate an exact preview, back up, and atomically delete owned records.

    This operation is intentionally distinct from completing/discarding a
    culture: it removes its history and frees its human-readable label.
    """
    if not db.in_transaction or db.total_changes:
        raise RuntimeError("Permanent deletion requires a fresh BEGIN IMMEDIATE transaction")
    preview = preview_container_deletion(db, cid)
    if confirmation_label != preview["label"]:
        raise HTTPException(422, "deletion_label_mismatch")
    if preview["blockers"]:
        raise HTTPException(409, "container_has_dependents")
    if fingerprint != preview["fingerprint"]:
        raise HTTPException(409, "deletion_preview_changed")

    backup_path = _backup_before_delete(db, backup_dir)
    db.execute("SAVEPOINT permanent_container_delete")
    try:
        for table in OWNED_TABLES:
            db.execute(f"DELETE FROM {table} WHERE container_id=?", (cid,))
        db.execute("DELETE FROM egg_batches WHERE source_id=?", (cid,))
        db.execute("DELETE FROM containers WHERE id=?", (cid,))
        db.execute("RELEASE SAVEPOINT permanent_container_delete")
    except Exception:
        db.execute("ROLLBACK TO SAVEPOINT permanent_container_delete")
        db.execute("RELEASE SAVEPOINT permanent_container_delete")
        raise
    return {"deleted": cid, "label": preview["label"], "counts": preview["counts"], "backup": backup_path.name}
