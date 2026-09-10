"""Validated SQLite workspace import, with a preview and recovery snapshot.

Only data from the supported eight tables is read. Uploaded schema, indexes,
triggers, and SQL are never executed against the personal workspace. Connection
configuration is machine-local and deliberately lives outside this format.
"""
import hashlib
import json
import math
import re
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool


MAX_UPLOAD_BYTES = 64 * 1024 * 1024
PREVIEW_LIFETIME_SECONDS = 15 * 60
MAX_STAGED_UPLOADS = 8
MAX_IMPORTED_RECORDS = 250000
RECOVERY_FILENAME = re.compile(r'flykeeper-before-restore-\d{8}T\d{12}Z-[0-9a-f]{8}\.db')
TABLE_COLUMNS = {
    'meta': ('key', 'value'),
    'containers': ('id', 'label', 'payload'),
    'temperatures': ('id', 'container_id', 'at', 'temperature'),
    'logs': ('id', 'container_id', 'at', 'action', 'notes'),
    'events': ('id', 'container_id', 'rule_key', 'payload'),
    'availability': ('date', 'payload'),
    'plans': ('id', 'container_id', 'payload'),
    'egg_batches': ('id', 'source_id', 'payload'),
}
# A trusted schema checks uniqueness, SQL foreign keys, and column constraints
# even if those constraints were stripped from an uploaded database.
VALIDATION_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE containers(id TEXT PRIMARY KEY, label TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
CREATE TABLE temperatures(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), at TEXT NOT NULL, temperature INTEGER NOT NULL CHECK(temperature IN (18,25)));
CREATE TABLE logs(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), at TEXT NOT NULL, action TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
CREATE TABLE events(id TEXT PRIMARY KEY, container_id TEXT REFERENCES containers(id), rule_key TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(container_id,rule_key));
CREATE TABLE availability(date TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE plans(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), payload TEXT NOT NULL);
CREATE TABLE egg_batches(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES containers(id), payload TEXT NOT NULL);
"""


def _invalid(detail='import_invalid_records'):
    raise HTTPException(422, detail)


def _text(value, maximum=10000, allow_empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not allow_empty and not value.strip()):
        _invalid()
    return value


def _stamp(value):
    if not isinstance(value, str) or 'T' not in value:
        _invalid()
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is not None:
        _invalid()
    return parsed


def _json_object(value):
    def reject_constant(_):
        _invalid()
    def unique_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                _invalid()
            result[key] = item
        return result
    parsed = json.loads(value, parse_constant=reject_constant, object_pairs_hook=unique_object)
    if not isinstance(parsed, dict):
        _invalid()
    return parsed


def _read_rows(db, maximum=None):
    result = {}
    total = 0
    for table, columns in TABLE_COLUMNS.items():
        limit = f' LIMIT {maximum - total + 1}' if maximum is not None else ''
        result[table] = [dict(zip(columns, row)) for row in db.execute(
            f"SELECT {','.join(columns)} FROM {table} ORDER BY {columns[0]}{limit}")]
        total += len(result[table])
        if maximum is not None and total > maximum:
            _invalid('import_too_many_records')
    return result


def _fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def workspace_fingerprint(db):
    """Hash persisted records; clock passage and file metadata do not stale a preview."""
    return _fingerprint(_read_rows(db))


def _summary(rows):
    settings = _json_object(next(row['value'] for row in rows['meta'] if row['key'] == 'settings'))
    return {'counts': {table: len(values) for table, values in rows.items() if table != 'meta'},
            'timezone': settings['timezone']}


def _check_schema(source, trusted):
    objects = source.execute("SELECT type,name,tbl_name,sql FROM sqlite_master").fetchall()
    tables = {row[1] for row in objects if row[0] == 'table'}
    if tables != set(TABLE_COLUMNS):
        _invalid('import_unsupported_schema')
    for kind, name, table, sql in objects:
        if kind not in ('table', 'index') or table not in TABLE_COLUMNS:
            _invalid('import_unsupported_schema')
        if kind == 'table' and (not sql or 'VIRTUAL' in sql.upper()):
            _invalid('import_unsupported_schema')
        if kind == 'index' and sql is not None:
            if name not in ('idx_temperatures_container_at', 'idx_logs_container_at'):
                _invalid('import_unsupported_schema')
            info = list(source.execute(f'PRAGMA index_info("{name}")'))
            if [row[2] for row in info] != ['container_id', 'at']:
                _invalid('import_unsupported_schema')
    for table in TABLE_COLUMNS:
        if list(source.execute(f'PRAGMA table_info({table})')) != list(trusted.execute(f'PRAGMA table_info({table})')):
            _invalid('import_unsupported_schema')


def _insert_rows(db, rows):
    for table, columns in TABLE_COLUMNS.items():
        db.executemany(f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                       [tuple(row[column] for column in columns) for row in rows[table]])


def _validate_records(rows, services):
    meta = {row['key']: row['value'] for row in rows['meta']}
    if meta.get('schema_version') != '1' or 'settings' not in meta:
        _invalid('import_unsupported_schema')
    for row in rows['meta']:
        _text(row['key'], 200)
        _text(row['value'], 100000, allow_empty=True)
    settings = _json_object(meta['settings'])
    services.SettingsInput.model_validate_json(json.dumps(settings), strict=True)
    # A backup cannot revive the obsolete multiple-day virgin collection rule.
    if settings.get('template', {}).get('collection_days') != 1:
        _invalid()
    containers, batches = {}, {}
    for row in rows['containers']:
        value = _json_object(row['payload'])
        required = {'id', 'label', 'kind', 'purpose', 'genotype', 'female_genotype', 'male_genotype',
                    'setup_date', 'setup_time', 'initial_temperature', 'temperature_policy', 'notes',
                    'template', 'parents', 'stage', 'transfer_index', 'cohort_id', 'source_id', 'status'}
        if not required.issubset(value) or value['id'] != row['id'] or value['label'] != row['label']:
            _invalid()
        _text(value['id'], 200)
        _text(value['label'], 80)
        _text(value['cohort_id'], 200)
        if value['status'] not in ('planned', 'active', 'completed', 'discarded'):
            _invalid()
        if value['template'].get('collection_days') != 1:
            _invalid()
        validation = dict(value)
        # Historical egg containers explicitly awaiting review remain editable
        # after restore; validation must not fabricate the missing observations.
        if value['kind'] == 'egg_laying':
            if value.get('genotype_review_required') is True and not value['genotype'].strip():
                validation['genotype'] = 'Pending review'
            if value.get('setup_time_review_required') is True and not value['setup_time']:
                validation['setup_time'] = '00:00'
        services.ContainerInput.model_validate_json(json.dumps(validation), strict=True)
        for key in ('first_eclosion_at',):
            if value.get(key) is not None:
                if _stamp(value[key]) < services.start_of(value):
                    _invalid()
        if value.get('adult_source') not in (None, 'parents', 'offspring'):
            _invalid()
        containers[row['id']] = value
    # Validate source links in payloads, which SQLite foreign keys cannot see.
    for cid, value in containers.items():
        source_id = value['source_id']
        if source_id is not None and source_id not in containers:
            _invalid()
        seen, cursor = {cid}, source_id
        while cursor is not None:
            if cursor in seen:
                _invalid()
            seen.add(cursor)
            cursor = containers[cursor]['source_id']
    for row in rows['egg_batches']:
        value = _json_object(row['payload'])
        if value.get('id') != row['id'] or value.get('source_id') != row['source_id']:
            _invalid()
        _text(value['id'], 200)
        services.EggBatchInput.model_validate_json(json.dumps(value), strict=True)
        source = containers[row['source_id']]
        if source['kind'] != 'egg_laying' or _stamp(value['lay_start']) < services.start_of(source):
            _invalid()
        if value.get('status') not in ('planned', 'collected', 'cancelled') or not isinstance(value.get('uses'), list):
            _invalid()
        collected = value.get('collected_at')
        if value['status'] == 'collected' and not collected:
            _invalid()
        if collected and _stamp(collected) < _stamp(value['lay_end']):
            _invalid()
        use_ids = set()
        for use in value['uses']:
            if not isinstance(use, dict) or use.get('id') in use_ids:
                _invalid()
            _text(use['id'], 200)
            use_ids.add(use['id'])
            services.EggBatchAction.model_validate_json(json.dumps({**use, 'action': 'use'}), strict=True)
            if not collected or _stamp(use['at']) < _stamp(collected):
                _invalid()
        batches[row['id']] = value
    for value in containers.values():
        if value.get('egg_batch_id'):
            batch = batches.get(value['egg_batch_id'])
            if not batch or value['kind'] != 'petri_dish' or value['source_id'] != batch['source_id']:
                _invalid()
            if not batch.get('collected_at') or _stamp(batch['collected_at']) > services.start_of(value):
                _invalid()
            if any(value['incubation'][key] != batch[key] for key in ('lay_start', 'lay_end')):
                _invalid()
        if value['kind'] == 'petri_dish' and _stamp(value['incubation']['lay_end']) > services.start_of(value):
            _invalid()
    for row in rows['availability']:
        value = _json_object(row['payload'])
        if value.get('date') != row['date']:
            _invalid()
        services.AvailabilityInput.model_validate_json(json.dumps(value), strict=True)
    for row in rows['logs']:
        _text(row['id'], 200)
        _stamp(row['at'])
        _text(row['action'], 200)
        _text(row['notes'], 11000, allow_empty=True)
    temperatures = {cid: [] for cid in containers}
    for row in rows['temperatures']:
        _text(row['id'], 200)
        if _stamp(row['at']) < services.start_of(containers[row['container_id']]):
            _invalid()
        temperatures[row['container_id']].append(row)
    for row in rows['events']:
        value = _json_object(row['payload'])
        if any(value.get(key) != row[key] for key in ('id', 'container_id', 'rule_key')):
            _invalid()
        _text(value['id'], 200)
        _text(value['rule_key'], 300)
        _text(value['title'], 200, allow_empty=True)
        if value.get('kind') not in ('custom', 'transfer', 'remove', 'check', 'tissue', 'stock', 'watch', 'collect',
                                     'score', 'third_instar', 'egg_setup', 'offspring_ready', 'first_instar',
                                     'cold', 'warm', 'egg_collect'):
            _invalid()
        if value.get('status') not in ('pending', 'done', 'skipped', 'disabled', 'cancelled'):
            _invalid()
        if value.get('basis') not in ('manual', 'calendar', 'development', 'hours'):
            _invalid()
        if type(value.get('critical')) is not bool or type(value.get('pinned')) is not bool:
            _invalid()
        if _stamp(value['end']) < _stamp(value['due']):
            _invalid()
        if value.get('egg_batch_id'):
            batch = batches.get(value['egg_batch_id'])
            if not batch or value['container_id'] != batch['source_id']:
                _invalid()
    for row in rows['plans']:
        value = _json_object(row['payload'])
        if value.get('id') != row['id'] or value.get('container_id') != row['container_id']:
            _invalid()
        if _stamp(value['warm_at']) <= _stamp(value['cold_at']):
            _invalid()
        if not isinstance(value.get('hours'), (int, float)) or not math.isfinite(value['hours']) or value['hours'] <= 0:
            _invalid()
        if not isinstance(value.get('events'), list):
            _invalid()
        for event in value['events']:
            if not isinstance(event, dict) or _stamp(event['end']) < _stamp(event['due']):
                _invalid()
    # Exercise pure forecast readers before accepting the file so nested values
    # used by the dashboard cannot turn a successful restore into a broken page.
    for value in containers.values():
        segments = sorted(temperatures[value['id']], key=lambda item: item['at'])
        services.generated_events(value, segments)


def validate_snapshot(path, services):
    """Read an upload in isolation and return validated data, never its SQL."""
    try:
        if path.stat().st_size > MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'import_file_too_large')
        with path.open('rb') as file:
            if file.read(16) != b'SQLite format 3\x00':
                _invalid('import_invalid_file')
        with closing(sqlite3.connect(':memory:')) as trusted:
            trusted.execute('PRAGMA foreign_keys=ON')
            trusted.executescript(VALIDATION_SCHEMA)
            with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as source:
                deadline = time.monotonic() + 10
                source.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
                source.execute('PRAGMA trusted_schema=OFF')
                source.execute('PRAGMA query_only=ON')
                _check_schema(source, trusted)
                if source.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                    _invalid('import_invalid_file')
                rows = _read_rows(source, MAX_IMPORTED_RECORDS)
            _insert_rows(trusted, rows)
            if trusted.execute('PRAGMA foreign_key_check').fetchall():
                _invalid()
            _validate_records(rows, services)
        return rows
    except HTTPException:
        raise
    except sqlite3.IntegrityError as error:
        raise HTTPException(422, 'import_invalid_records') from error
    except (sqlite3.Error, OSError) as error:
        raise HTTPException(422, 'import_invalid_file') from error
    except (ValidationError, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError) as error:
        raise HTTPException(422, 'import_invalid_records') from error


def backup_current_workspace(db, backup_dir):
    """The caller holds BEGIN IMMEDIATE and has made no writes yet."""
    source_path = next((row[2] for row in db.execute('PRAGMA database_list') if row[1] == 'main'), '')
    target_path = None
    created = False
    try:
        if not source_path:
            raise OSError('A file-backed workspace is required')
        folder = Path(backup_dir)
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target_path = folder / f'flykeeper-before-restore-{stamp}-{secrets.token_hex(4)}.db'
        with target_path.open('xb'):
            created = True
        with closing(sqlite3.connect(source_path, timeout=20)) as source:
            with closing(sqlite3.connect(target_path)) as target:
                source.backup(target)
                if target.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise sqlite3.DatabaseError('Recovery snapshot failed validation')
        return target_path
    except (OSError, sqlite3.Error) as error:
        if target_path is not None and created:
            try:
                target_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise HTTPException(500, 'import_backup_failed') from error


class RestoreInput(BaseModel):
    token: str = Field(min_length=1, max_length=100)
    confirmation: str = Field(max_length=100)
    expected_current_fingerprint: str = Field(min_length=1, max_length=100)


@dataclass
class StagedUpload:
    path: Path
    workspace: Path
    expires_at: datetime
    current_fingerprint: str
    incoming_fingerprint: str
    timer: threading.Timer | None = None
    result: dict | None = None


class WorkspaceImporter:
    def __init__(self, services, backup_dir=None):
        self.services = services
        self.backup_dir = backup_dir
        self._directory = TemporaryDirectory(prefix='flykeeper-import-')
        self._staged = {}
        self._lock = threading.RLock()
        self._closed = False

    def open(self):
        with self._lock:
            if self._closed:
                self._directory = TemporaryDirectory(prefix='flykeeper-import-')
                self._closed = False

    def _remove(self, token):
        with self._lock:
            staged = self._staged.pop(token, None)
            if staged:
                if staged.timer:
                    staged.timer.cancel()
                staged.path.unlink(missing_ok=True)

    def close(self):
        with self._lock:
            for token in list(self._staged):
                self._remove(token)
            self._directory.cleanup()
            self._closed = True

    def preview(self, payload):
        self.open()
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, 'import_file_too_large')
        path = Path(self._directory.name) / (secrets.token_hex(24) + '.db')
        try:
            path.write_bytes(payload)
            rows = validate_snapshot(path, self.services)
            with self.services.database() as db:
                current = _read_rows(db)
            fingerprint = _fingerprint(current)
            expires = datetime.now(timezone.utc) + timedelta(seconds=PREVIEW_LIFETIME_SECONDS)
            token = secrets.token_urlsafe(32)
            staged = StagedUpload(path, Path(self.services.DB_PATH).resolve(), expires, fingerprint, _fingerprint(rows))
            with self._lock:
                while len(self._staged) >= MAX_STAGED_UPLOADS:
                    self._remove(next(iter(self._staged)))
                self._staged[token] = staged
                staged.timer = threading.Timer(PREVIEW_LIFETIME_SECONDS, self._remove, args=(token,))
                staged.timer.daemon = True
                staged.timer.start()
            return {'token': token, 'expires_at': expires.isoformat(), 'incoming': _summary(rows),
                    'current': _summary(current), 'current_fingerprint': fingerprint}
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def restore(self, model):
        if model.confirmation != 'RESTORE':
            raise HTTPException(422, 'import_confirmation_required')
        with self._lock:
            staged = self._staged.get(model.token)
            if not staged or staged.expires_at <= datetime.now(timezone.utc) or staged.workspace != Path(self.services.DB_PATH).resolve():
                self._remove(model.token)
                raise HTTPException(410, 'import_upload_expired')
            if model.expected_current_fingerprint != staged.current_fingerprint:
                raise HTTPException(409, 'import_workspace_changed')
            if staged.result is not None:
                return staged.result
            rows = validate_snapshot(staged.path, self.services)
            if _fingerprint(rows) != staged.incoming_fingerprint:
                self._remove(model.token)
                raise HTTPException(409, 'import_invalid_file')
            try:
                with self.services.database() as db:
                    current = workspace_fingerprint(db)
                    if current != staged.current_fingerprint or current != model.expected_current_fingerprint:
                        raise HTTPException(409, 'import_workspace_changed')
                    backup = backup_current_workspace(db, self.backup_dir or self.services.ROOT / 'backups')
                    for table in reversed(TABLE_COLUMNS):
                        db.execute(f'DELETE FROM {table}')
                    _insert_rows(db, rows)
                    if db.execute('PRAGMA foreign_key_check').fetchall():
                        raise sqlite3.IntegrityError('Restore left dangling references')
            except sqlite3.Error as error:
                raise HTTPException(500, 'import_restore_failed') from error
            staged.result = {'restored': True, 'counts': _summary(rows)['counts'], 'backup': backup.name}
            staged.path.unlink(missing_ok=True)
            return staged.result

    def recovery_file(self, filename):
        if not RECOVERY_FILENAME.fullmatch(filename):
            raise HTTPException(404, 'import_recovery_not_found')
        try:
            folder = Path(self.backup_dir or self.services.ROOT / 'backups').resolve(strict=True)
            candidate = folder / filename
            resolved = candidate.resolve(strict=True)
            if candidate.is_symlink() or resolved.parent != folder or resolved.name != filename or not resolved.is_file():
                raise HTTPException(404, 'import_recovery_not_found')
            with resolved.open('rb') as source:
                if source.read(16) != b'SQLite format 3\x00':
                    raise HTTPException(404, 'import_recovery_not_found')
            return resolved
        except (OSError, RuntimeError, ValueError):
            raise HTTPException(404, 'import_recovery_not_found') from None


def make_router(services):
    """Pass the app module after model definitions; include before static files."""
    importer = WorkspaceImporter(services)

    @asynccontextmanager
    async def lifespan(_app):
        importer.open()
        try:
            yield
        finally:
            importer.close()

    router = APIRouter(lifespan=lifespan)

    @router.post('/api/import/preview')
    async def preview(request: Request):
        media_type = request.headers.get('content-type', '').split(';', 1)[0].strip().lower()
        if media_type not in ('application/octet-stream', 'application/vnd.sqlite3', 'application/x-sqlite3'):
            raise HTTPException(415, 'import_unsupported_type')
        length = request.headers.get('content-length')
        if length:
            try:
                if int(length) > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, 'import_file_too_large')
            except ValueError:
                raise HTTPException(400, 'import_invalid_file')
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
                raise HTTPException(413, 'import_file_too_large')
            data.extend(chunk)
        return await run_in_threadpool(importer.preview, bytes(data))

    @router.post('/api/import/restore')
    def restore(model: RestoreInput):
        return importer.restore(model)

    @router.get('/api/import/recovery/{filename}')
    def recovery(filename: str):
        return FileResponse(importer.recovery_file(filename), media_type='application/vnd.sqlite3', filename=filename)

    return router
