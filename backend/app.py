"""Local-only Flykeeper API. All dates/times use the configured laboratory zone."""
import json
import os
import sqlite3
import sys
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, NaiveDatetime, field_validator, model_validator
from .domain import (DEFAULT_SETTINGS, DEFAULT_TEMPLATE, start_of, parse, effective_age,
                     generated_events, event_conflict, virgin_clock, suggest_cooling, incubation_window, eclosion_estimate)
from .container_cleanup import preview_container_deletion, delete_container_permanently, next_container_label
from . import activity_cleanup, activity_record_cleanup

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("FLYKEEPER_DB", ROOT / "data" / "flykeeper.db"))
app = FastAPI(title="Flykeeper", version="0.1.0")

def uid():
    return uuid.uuid4().hex[:16]

def dump(value):
    return json.dumps(value, ensure_ascii=False)

@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=20)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db():
    with database() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS containers(id TEXT PRIMARY KEY, label TEXT UNIQUE NOT NULL, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS temperatures(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), at TEXT NOT NULL, temperature INTEGER NOT NULL CHECK(temperature IN (18,25)));
        CREATE INDEX IF NOT EXISTS idx_temperatures_container_at ON temperatures(container_id, at);
        CREATE TABLE IF NOT EXISTS logs(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), at TEXT NOT NULL, action TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_logs_container_at ON logs(container_id, at);
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, container_id TEXT REFERENCES containers(id), rule_key TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(container_id,rule_key));
        CREATE TABLE IF NOT EXISTS availability(date TEXT PRIMARY KEY, payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY, container_id TEXT NOT NULL REFERENCES containers(id), payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS egg_batches(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES containers(id), payload TEXT NOT NULL);
        """)
        db.execute("INSERT OR IGNORE INTO meta VALUES('settings',?)", (dump(DEFAULT_SETTINGS),))
        db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")
        if not db.execute("SELECT 1 FROM meta WHERE key='single_day_collection_v1'").fetchone():
            settings = json.loads(db.execute("SELECT value FROM meta WHERE key='settings'").fetchone()[0])
            settings['template']['collection_days'] = 1
            db.execute("UPDATE meta SET value=? WHERE key='settings'", (dump(settings),))
            for row in db.execute('SELECT id,payload FROM containers').fetchall():
                value = json.loads(row['payload'])
                value['template']['collection_days'] = 1
                db.execute('UPDATE containers SET payload=? WHERE id=?', (dump(value), row['id']))
            db.execute("INSERT INTO meta VALUES('single_day_collection_v1','1')")
        if not db.execute("SELECT 1 FROM meta WHERE key='known_egg_adults_v1'").fetchone():
            for row in db.execute('SELECT id,payload FROM containers').fetchall():
                value = json.loads(row['payload'])
                if value['kind'] != 'egg_laying':
                    continue
                known = value.get('genotype', '').strip()
                female, male = value.get('female_genotype', '').strip(), value.get('male_genotype', '').strip()
                if not known and female and female == male:
                    known = female
                value['genotype'] = known
                value['genotype_review_required'] = not bool(known)
                value['setup_time_review_required'] = not bool(value.get('setup_time'))
                relation = value.get('source_relation')
                if relation in ('egg_laying_transfer', 'egg_laying_generation'):
                    value['adult_source'] = 'parents' if relation == 'egg_laying_transfer' else 'offspring'
                # Preserve historical parent fields and source changes; their meaning cannot be inferred safely.
                db.execute('UPDATE containers SET payload=? WHERE id=?', (dump(value), row['id']))
            db.execute("INSERT INTO meta VALUES('known_egg_adults_v1','1')")

init_db()

def settings_of(db):
    return json.loads(db.execute("SELECT value FROM meta WHERE key='settings'").fetchone()[0])

def now_of(db):
    return datetime.now(ZoneInfo(settings_of(db)["timezone"])).replace(tzinfo=None, second=0, microsecond=0)

def get_container(db, cid):
    row = db.execute("SELECT payload FROM containers WHERE id=?", (cid,)).fetchone()
    if not row:
        raise HTTPException(404, "container_not_found")
    return json.loads(row[0])

def save_container(db, container):
    try:
        db.execute("INSERT INTO containers VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,payload=excluded.payload",
                   (container["id"], container["label"], dump(container)))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "label_exists")

def temperatures_of(db, cid):
    return [dict(x) for x in db.execute("SELECT * FROM temperatures WHERE container_id=? ORDER BY at", (cid,))]

def temperature_at(db, container, at):
    current = container['initial_temperature']
    for segment in temperatures_of(db, container['id']):
        if parse(segment['at']) > at:
            break
        current = segment['temperature']
    return current

def logs_of(db, cid):
    return [dict(x) for x in db.execute("SELECT * FROM logs WHERE container_id=? ORDER BY at", (cid,))]

def log(db, cid, action, at, notes=""):
    db.execute("INSERT INTO logs VALUES(?,?,?,?,?)", (uid(), cid, at, action, notes))

def save_event(db, event):
    db.execute("INSERT INTO events VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET rule_key=excluded.rule_key,payload=excluded.payload",
               (event["id"], event.get("container_id"), event["rule_key"], dump(event)))

def reconcile(db, container):
    # Upgrade legacy positional collection keys without changing event identity/history.
    for row in db.execute('SELECT payload FROM events WHERE container_id=?', (container['id'],)).fetchall():
        old = json.loads(row[0])
        parts = old['rule_key'].split('-')
        if len(parts) == 3 and parts[0] == 'collect' and parts[2].isdigit():
            index = int(parts[2])
            windows = container['template']['windows']
            window = windows[index] if old['pinned'] and index < len(windows) else [old['due'][11:16], old['end'][11:16]]
            old['rule_key'] = f'collect-{parts[1]}-{window[0]}-{window[1]}'
            save_event(db, old)
    generation_input = container
    if container['kind'] == 'egg_laying' and container.get('source_id'):
        source = get_container(db, container['source_id'])
        generation_input = {**container, 'source_eclosion_estimate': eclosion_estimate(source, temperatures_of(db, source['id'])),
                            'source_collection_windows': source['template']['windows']}
    generated = generated_events(generation_input, temperatures_of(db, container["id"]))
    existing = {x["rule_key"]: json.loads(x["payload"]) for x in db.execute("SELECT * FROM events WHERE container_id=?", (container["id"],))}
    expected = {e["rule_key"] for e in generated}
    for raw in generated:
        old = existing.get(raw["rule_key"])
        if old and 'timing_review' in raw and old.get('timing_review') != raw['timing_review']:
            old['timing_review'] = raw['timing_review']
            save_event(db, old)
        if old and old['status'] == 'cancelled' and old.get('cancel_reason', 'rule_removed') == 'rule_removed':
            old['status'] = 'pending'
            old.pop('cancel_reason', None)
            save_event(db, old)
        if old and (old["status"] != "pending" or old["pinned"]):
            continue
        event = {**raw, "id": old["id"] if old else uid(), "container_id": container["id"], "status": "pending", "pinned": False}
        save_event(db, event)
    for key, old in existing.items():
        if key not in expected and old["status"] == "pending" and not key.startswith(("custom-", "plan-")):
            old["status"] = "cancelled"
            old['cancel_reason'] = 'rule_removed'
            save_event(db, old)

def validate_windows(windows):
    from datetime import time
    previous = "00:00"
    for pair in windows:
        if len(pair) != 2:
            raise ValueError("invalid_windows")
        a, b = pair
        time.fromisoformat(a)
        time.fromisoformat(b)
        if len(a) != 5 or len(b) != 5 or a >= b or a < previous:
            raise ValueError("invalid_windows")
        previous = b
    return windows

class Template(BaseModel):
    transfer_day: int = Field(3, ge=1, le=30)
    max_transfers: int = Field(2, ge=0, le=20)
    check_day: int = Field(6, ge=1, le=60)
    collection_day: int = Field(10, ge=1, le=90)
    collection_days: Literal[1] = 1
    stock_interval: int = Field(11, ge=1, le=90)
    watch_day: int = Field(9, ge=1, le=89)
    windows: list[list[str]] = Field(default_factory=lambda: DEFAULT_TEMPLATE["windows"], min_length=1, max_length=8)
    rate18: float = Field(0.5, ge=0.01, le=0.99)
    virgin_hours25: int = Field(8, ge=1, le=24)
    virgin_hours18: int = Field(16, ge=1, le=36)
    _windows = field_validator("windows")(validate_windows)

    @model_validator(mode="after")
    def check_order(self):
        if self.watch_day > self.collection_day:
            raise ValueError("watch_after_collection")
        return self

class Incubation(BaseModel):
    lay_start: NaiveDatetime
    lay_end: NaiveDatetime
    min_hours: float = Field(24, ge=0, le=720)
    max_hours: float = Field(30, gt=0, le=720)
    reference_temperature: Literal[18, 25] = 25
    lay_temperature: Literal[18, 25] = 25

    @model_validator(mode='after')
    def order(self):
        if self.lay_end < self.lay_start or self.max_hours < self.min_hours:
            raise ValueError('invalid_incubation_interval')
        return self

class ContainerInput(BaseModel):
    label: str = Field("", max_length=80)
    kind: Literal["vial", "bottle", "petri_dish", "egg_laying"] = "vial"
    purpose: Literal["stock", "cross", "virgin", "larvae", "egg_laying", "dissection", "imaging", "other"] = "cross"
    genotype: str = Field("", max_length=1000)
    female_genotype: str = Field("", max_length=1000)
    male_genotype: str = Field("", max_length=1000)
    setup_date: date
    setup_time: str | None = None
    initial_temperature: Literal[18, 25] = 25
    temperature_policy: Literal["allowed", "forbidden"] = "allowed"
    notes: str = Field("", max_length=10000)
    template: Template | None = None
    parents: Literal['present', 'removed', 'transferred'] = 'present'
    stage: Literal['unobserved', 'larvae', 'pupae', 'eclosion', 'first_instar'] = 'unobserved'
    transfer_index: int = Field(0, ge=0, le=20)
    initial_status: Literal['auto', 'active', 'planned'] = 'auto'
    incubation: Incubation | None = None
    egg_batch_id: str | None = None
    workflow: 'Workflow | None' = None

    @field_validator("setup_time")
    @classmethod
    def valid_time(cls, value):
        from datetime import time
        if value:
            time.fromisoformat(value)
            if len(value) != 5:
                raise ValueError("invalid_time")
        return value or None

    @model_validator(mode="after")
    def genotype_required(self):
        if self.kind == 'petri_dish':
            if self.purpose not in ('dissection', 'imaging', 'other') or not self.incubation or not self.setup_time:
                raise ValueError('dish_protocol_required')
        elif self.kind == 'egg_laying':
            if self.purpose != 'egg_laying':
                raise ValueError('laying_purpose_required')
            if not self.setup_time:
                raise ValueError('egg_setup_time_required')
        elif self.purpose not in ('stock', 'cross', 'virgin', 'larvae'):
            raise ValueError('invalid_purpose')
        if self.kind != 'petri_dish' and (self.incubation or self.egg_batch_id):
            raise ValueError('invalid_egg_source')
        if self.purpose == 'cross':
            if not self.female_genotype.strip() or not self.male_genotype.strip():
                raise ValueError("parent_genotypes_required")
        elif not self.genotype.strip():
            raise ValueError("genotype_required")
        return self

class Workflow(BaseModel):
    cross_goal: Literal['score', 'virgins', 'third_instar'] = 'score'
    transfer_enabled: bool = True
    remove_day: int = Field(5, ge=1, le=30)
    selection_day: int = Field(10, ge=1, le=90)
    selection_days: int = Field(1, ge=1, le=14)
    selection_window: list[str] = Field(default_factory=lambda: ['09:00', '17:00'], min_length=2, max_length=2)
    third_instar_day: int = Field(5, ge=1, le=90)
    third_instar_window: list[str] = Field(default_factory=lambda: ['09:00', '17:00'], min_length=2, max_length=2)
    target_genotype: str = Field('', max_length=1000)
    selection_notes: str = Field('', max_length=3000)
    female_virgins: Literal['unconfirmed', 'confirmed'] = 'unconfirmed'
    follow_eclosion: bool = True

    @field_validator('selection_window', 'third_instar_window')
    @classmethod
    def valid_selection_window(cls, value):
        validate_windows([value])
        return value

ContainerInput.model_rebuild()


def create_container(db, model, parent=None, same_cohort=False):
    value = model.model_dump(mode="json")
    if value['kind'] == 'egg_laying':
        value.update(genotype=value['genotype'].strip(), female_genotype='', male_genotype='',
                     genotype_review_required=False, setup_time_review_required=False)
    if value['workflow'] is None and value['kind'] in ('vial', 'bottle'):
        value['workflow'] = Workflow(transfer_enabled=value['purpose'] != 'stock').model_dump(mode='json')
    cid = uid()
    if not value["label"].strip():
        value['label'] = next_container_label(db, value['kind'])
    future = parse(value['setup_date'] + 'T' + (value.get('setup_time') or '00:00')) > now_of(db)
    initial_status = value.pop('initial_status')
    if future and initial_status == 'active':
        raise HTTPException(422, 'future_active_setup')
    value.update(id=cid, label=value["label"].strip(), template=value["template"] or settings_of(db)["template"],
                 cohort_id=parent["cohort_id"] if same_cohort else uid(),
                 transfer_index=parent["transfer_index"] + 1 if same_cohort else (0 if parent else value['transfer_index']),
                 source_id=parent["id"] if parent else None,
                 status=('planned' if future else 'active') if initial_status == 'auto' else initial_status)
    if parent:
        value.update(parents='present', stage='unobserved')
        if value['kind'] != 'egg_laying':
            value['status'] = 'active'
    if value['kind'] == 'petri_dish':
        if value['egg_batch_id']:
            batch = get_egg_batch(db, value['egg_batch_id'])
            if batch['status'] != 'collected' or parse(batch['collected_at']) > start_of(value):
                raise HTTPException(409, 'eggs_not_collected')
            value['incubation'].update(lay_start=batch['lay_start'], lay_end=batch['lay_end'], lay_temperature=batch['temperature'])
            value['source_id'] = batch['source_id']
        if parse(value['incubation']['lay_end']) > start_of(value):
            raise HTTPException(422, 'egg_window_after_setup')
        value.update(parents='removed', transfer_index=0)
    save_container(db, value)
    log(db, cid, "created", now_of(db).isoformat(timespec="minutes"))
    reconcile(db, value)
    return value

@app.middleware("http")
async def local_only(request: Request, call_next):
    from urllib.parse import urlparse
    host = request.url.hostname
    origin = request.headers.get("origin")
    if host not in ("127.0.0.1", "localhost", "testserver") or (origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost")):
        return JSONResponse({"detail": "local_only"}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api/") else "no-cache"
    return response

@app.get("/api/health")
def health():
    return {"status": "ok", "app": "flykeeper", "version": "0.1.0", "instance": getattr(app.state, 'instance', None)}

@app.get('/api/runtime')
def runtime():
    return {'managed': hasattr(app.state, 'request_shutdown'), 'token': getattr(app.state, 'shutdown_token', None)}

class ShutdownInput(BaseModel):
    token: str

@app.post('/api/shutdown')
def shutdown(model: ShutdownInput, background: BackgroundTasks):
    import secrets
    expected = getattr(app.state, 'shutdown_token', None)
    if not expected or not secrets.compare_digest(expected, model.token):
        raise HTTPException(403, 'shutdown_unavailable')
    background.add_task(app.state.request_shutdown)
    return {'ok': True}

@app.get("/api/state")
def state():
    with database() as db:
        settings = settings_of(db)
        now = now_of(db)
        exceptions = [json.loads(x[0]) for x in db.execute("SELECT payload FROM availability ORDER BY date")]
        containers = [json.loads(x[0]) for x in db.execute("SELECT payload FROM containers ORDER BY label")]
        for c in containers:
            reconcile(db, c)
            temps = temperatures_of(db, c["id"])
            c["temperatures"], c["logs"] = temps, logs_of(db, c["id"])
            c["temperature"] = temps[-1]["temperature"] if temps else c["initial_temperature"]
            c["calendar_day"] = (now.date() - date.fromisoformat(c["setup_date"])).days
            c["effective_age"] = round(effective_age(c, temps, now), 1)
            c["clock"] = virgin_clock(c, temps, c["logs"], now)
            if c['kind'] in ('vial', 'bottle'):
                c['eclosion_estimate'] = eclosion_estimate(c, temps)
            if c['kind'] == 'egg_laying':
                c['genotype_review_required'] = not bool(c.get('genotype', '').strip())
                c['setup_time_review_required'] = not bool(c.get('setup_time'))
                source = next((item for item in containers if item['id'] == c.get('source_id')), None)
                c['source_eclosion_estimate'] = eclosion_estimate(source, temperatures_of(db, source['id'])) if source else None
            if c['kind'] == 'petri_dish':
                c['incubation_window'] = incubation_window(c, temps)
                c['egg_age_hours'] = [round((now - parse(c['incubation'][key])).total_seconds()/3600, 1) for key in ('lay_end', 'lay_start')]
        events = [json.loads(x[0]) for x in db.execute("SELECT payload FROM events")]
        for e in events:
            e["conflict"] = e["status"] == "pending" and event_conflict(e, settings, exceptions)
        return {"containers": containers, "events": sorted(events, key=lambda e: e["due"]), "settings": settings,
                "availability": exceptions, "plans": [json.loads(x[0]) for x in db.execute("SELECT payload FROM plans")],
                "now": now.isoformat(timespec="minutes"), 'egg_batches': [json.loads(x[0]) for x in db.execute('SELECT payload FROM egg_batches')]}

@app.post("/api/containers")
def new_container(model: ContainerInput):
    with database() as db:
        return create_container(db, model)

@app.get('/api/containers/{cid}/delete-preview')
def delete_preview(cid: str):
    with database() as db:
        return preview_container_deletion(db, cid)

class DeleteContainerInput(BaseModel):
    confirmation_label: str
    fingerprint: str

@app.delete('/api/containers/{cid}')
def delete_container(cid: str, model: DeleteContainerInput):
    with database() as db:
        return delete_container_permanently(db, cid, model.confirmation_label, model.fingerprint, ROOT / 'backups')

class DeleteActivityInput(BaseModel):
    fingerprint: str
    mode: Literal['undo', 'keep_later'] = 'undo'
    corrections: dict[str, str] = Field(default_factory=dict)
    reopen_event_ids: list[str] = Field(default_factory=list)

@app.get('/api/containers/{cid}/activities/{lid}/delete-preview')
def activity_delete_preview(cid: str, lid: str):
    with database() as db:
        return activity_record_cleanup.preview_activity_deletion(db, cid, lid, sys.modules[__name__])

@app.delete('/api/containers/{cid}/activities/{lid}')
def activity_delete(cid: str, lid: str, model: DeleteActivityInput):
    with database() as db:
        if model.mode == 'keep_later':
            if model.corrections or model.reopen_event_ids:
                raise HTTPException(422, 'activity_record_only_invalid')
            return activity_record_cleanup.delete_activity_record(db, cid, lid, model.fingerprint, ROOT / 'backups')
        activity_record_cleanup.require_no_deleted_log_restoration(db, cid, lid)
        return activity_cleanup.delete_activity(db, cid, lid, model.fingerprint,
            model.corrections, model.reopen_event_ids, ROOT / 'backups', reconcile, get_container, sys.modules[__name__])

class EditContainer(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    genotype: str = Field("", max_length=1000)
    female_genotype: str = Field("", max_length=1000)
    male_genotype: str = Field("", max_length=1000)
    notes: str = Field("", max_length=10000)
    temperature_policy: Literal["allowed", "forbidden"]
    template: Template
    setup_date: date | None = None
    setup_time: str | None = None
    incubation: Incubation | None = None
    workflow: Workflow | None = None

    @field_validator("setup_time")
    @classmethod
    def valid_time(cls, value):
        return ContainerInput.valid_time(value)

@app.put("/api/containers/{cid}")
def edit_container(cid: str, model: EditContainer):
    with database() as db:
        c = get_container(db, cid)
        reconcile(db, c)
        changes = model.model_dump(mode="json", exclude={"setup_date", "setup_time", "incubation", "workflow"})
        if model.workflow is not None:
            # An explicit workflow switch preserves manually pinned instructions as custom work.
            if c.get('workflow') != model.workflow.model_dump(mode='json'):
                proposed = {**c, 'workflow': model.workflow.model_dump(mode='json'), 'template': model.template.model_dump(mode='json')}
                expected = {event['rule_key'] for event in generated_events(proposed, temperatures_of(db, cid))}
                for row in db.execute('SELECT payload FROM events WHERE container_id=?', (cid,)).fetchall():
                    event = json.loads(row[0])
                    if event['rule_key'] == 'transfer' and not model.workflow.transfer_enabled:
                        # Cancelling the schedule also cancels a rescheduled transfer;
                        # retain its rule and manual time so re-enabling restores it.
                        continue
                    if event['status'] == 'pending' and event['pinned'] and event['rule_key'] not in expected and not event['rule_key'].startswith(('custom-', 'plan-')):
                        event.update(rule_key='custom-preserved-' + event['id'], basis='manual')
                        save_event(db, event)
            changes['workflow'] = model.workflow.model_dump(mode='json')
        changes['label'] = changes['label'].strip()
        if not changes["label"].strip():
            raise HTTPException(422, "invalid_label")
        if c["purpose"] == 'cross' and (not changes["female_genotype"].strip() or not changes["male_genotype"].strip()):
            raise HTTPException(422, "parent_genotypes_required")
        if c["purpose"] != 'cross' and not changes["genotype"].strip():
            raise HTTPException(422, "genotype_required")
        if c["status"] == "planned" and model.setup_date:
            changes.update(setup_date=model.setup_date.isoformat(), setup_time=model.setup_time if 'setup_time' in model.model_fields_set else c.get('setup_time'))
        if c['kind'] == 'egg_laying':
            changes['genotype'] = changes['genotype'].strip()
            if 'setup_time' in model.model_fields_set and not model.setup_time:
                raise HTTPException(422, 'egg_setup_time_required')
            if c['status'] != 'planned' and c.get('setup_time'):
                if ((model.setup_date and model.setup_date.isoformat() != c['setup_date']) or
                        (model.setup_time and model.setup_time != c['setup_time'])):
                    raise HTTPException(422, 'invalid_action_time')
            # The old parent strings remain historical context until explicitly corrected.
            changes.update(female_genotype=c.get('female_genotype', ''), male_genotype=c.get('male_genotype', ''))
            if c['status'] == 'planned' and 'setup_time' in model.model_fields_set:
                changes['setup_time'] = model.setup_time
            if c['status'] != 'planned' and not c.get('setup_time'):
                if model.setup_date and model.setup_date.isoformat() != c['setup_date']:
                    raise HTTPException(422, 'invalid_action_time')
                changes['setup_time'] = model.setup_time
                proposed = {**c, **changes}
                at = start_of(proposed)
                if at > now_of(db):
                    raise HTTPException(422, 'invalid_action_time')
                recorded = [parse(item['at']) for item in logs_of(db, cid) if item['action'] != 'created']
                recorded += [parse(item['at']) for item in temperatures_of(db, cid)]
                recorded += [parse(json.loads(row[0])['lay_start']) for row in db.execute('SELECT payload FROM egg_batches WHERE source_id=?', (cid,))]
                if any(at > stamp for stamp in recorded):
                    raise HTTPException(422, 'egg_setup_after_recorded_activity')
            if not changes.get('setup_time', c.get('setup_time')):
                raise HTTPException(422, 'egg_setup_time_required')
            if c.get('source_id'):
                source = get_container(db, c['source_id'])
                if start_of({**c, **changes}) < start_of(source):
                    raise HTTPException(422, 'invalid_action_time')
            changes.update(genotype_review_required=False, setup_time_review_required=False)
        c.update(changes)
        if c['kind'] == 'petri_dish' and model.incubation:
            protocol = model.incubation.model_dump(mode='json')
            if c.get('egg_batch_id'):
                for key in ('lay_start', 'lay_end', 'lay_temperature'):
                    protocol[key] = c['incubation'][key]
            if parse(protocol['lay_end']) > start_of(c):
                raise HTTPException(422, 'egg_window_after_setup')
            c['incubation'] = protocol
        save_container(db, c)
        reconcile(db, c)
        return c

class TransferInput(ContainerInput):
    mode: Literal["transfer", "generation"] = "transfer"

@app.post("/api/containers/{cid}/transfer")
def transfer(cid: str, model: TransferInput):
    with database() as db:
        activity_before = activity_cleanup.snapshot(db)
        c = get_container(db, cid)
        if c['kind'] in ('petri_dish', 'egg_laying') or model.kind in ('petri_dish', 'egg_laying'):
            raise HTTPException(409, 'use_egg_workflow')
        at = parse(model.setup_date.isoformat() + "T" + (model.setup_time or "00:00"))
        if at < start_of(c) or at > now_of(db):
            raise HTTPException(422, "invalid_action_time")
        if c["status"] != "active":
            raise HTTPException(409, "container_inactive")
        same = model.mode == "transfer"
        if same and (c["parents"] != "present" or c["transfer_index"] >= c["template"]["max_transfers"]):
            raise HTTPException(409, "transfer_unavailable")
        data = model.model_dump(exclude={"mode"})
        if 'temperature_policy' not in model.model_fields_set:
            data['temperature_policy'] = c['temperature_policy']
        if model.template is None:
            data['template'] = c['template']
        if same:
            data.update(female_genotype=c["female_genotype"], male_genotype=c["male_genotype"], genotype=c["genotype"], purpose=c["purpose"])
        if model.workflow is None and (same or model.purpose == c['purpose']):
            data['workflow'] = {**(c.get('workflow') or Workflow(cross_goal='virgins', transfer_enabled=True).model_dump(mode='json'))}
            if same:
                # Recording a transfer starts a continuation schedule in the
                # destination; an explicitly submitted opt-out still wins.
                data['workflow']['transfer_enabled'] = True
        child = create_container(db, ContainerInput(**data), c, same)
        if same:
            c["parents"] = "transferred"
            save_container(db, c)
        log(db, cid, "transfer" if same else "generation", at.isoformat(timespec="minutes"), child["label"])
        for row in db.execute("SELECT payload FROM events WHERE container_id=? AND rule_key=?", (cid, "transfer" if same else "stock")).fetchall():
            e = json.loads(row[0])
            e["status"] = "done"
            save_event(db, e)
        reconcile(db, c)
        activity_cleanup.record(db, activity_before, cid)
        return child

class EggLayingFromInput(BaseModel):
    adult_source: Literal['parents', 'offspring']
    genotype: str = Field(min_length=1, max_length=1000)
    label: str = Field('', max_length=80)
    setup_date: date
    setup_time: str
    initial_status: Literal['active', 'planned'] = 'active'
    initial_temperature: Literal[18, 25] | None = None
    temperature_policy: Literal['allowed', 'forbidden'] | None = None
    notes: str | None = Field(None, max_length=10000)

    @field_validator('setup_time')
    @classmethod
    def valid_time(cls, value):
        value = ContainerInput.valid_time(value)
        if not value:
            raise ValueError('egg_setup_time_required')
        return value

    @field_validator('genotype')
    @classmethod
    def known_genotype(cls, value):
        if not value.strip():
            raise ValueError('genotype_required')
        return value.strip()


@app.post('/api/containers/{cid}/egg-laying')
def egg_laying_from_container(cid: str, model: EggLayingFromInput):
    with database() as db:
        activity_before = activity_cleanup.snapshot(db)
        source = get_container(db, cid)
        if source['kind'] not in ('vial', 'bottle'):
            raise HTTPException(409, 'egg_laying_source_required')
        planned = model.initial_status == 'planned'
        if source['status'] != 'active' and not (source['status'] == 'planned' and planned and model.adult_source == 'offspring'):
            raise HTTPException(409, 'container_inactive')
        at = parse(model.setup_date.isoformat() + 'T' + model.setup_time)
        if at < start_of(source) or (not planned and at > now_of(db)):
            raise HTTPException(422, 'invalid_action_time')
        same = model.adult_source == 'parents'
        temperature = temperature_at(db, source, at)
        child = create_container(db, ContainerInput(
            label=model.label, kind='egg_laying', purpose='egg_laying',
            genotype=model.genotype,
            setup_date=model.setup_date, setup_time=model.setup_time,
            initial_status=model.initial_status,
            initial_temperature=model.initial_temperature if model.initial_temperature is not None else temperature,
            temperature_policy=model.temperature_policy if model.temperature_policy is not None else source['temperature_policy'],
            notes=model.notes if model.notes is not None else source['notes'], template=source['template'],
        ), source, same)
        child['adult_source'] = model.adult_source
        child['source_relation'] = 'egg_laying_' + model.adult_source
        child['inherit_source_temperature'] = model.initial_temperature is None
        save_container(db, child)
        reconcile(db, child)
        # Selecting adults never asserts that every parent was moved or completes source work.
        if not planned:
            log(db, cid, child['source_relation'], at.isoformat(timespec='minutes'), child['label'])
            activity_cleanup.record(db, activity_before, cid)
        return child


class ActionInput(BaseModel):
    action: Literal["remove", "clear", "collect", "tissue", "larvae", "pupae", "eclosion", "cold", "warm", "complete", "discard", "activate", "first_instar", "dissect", "image", "score", "third_instar"]
    at: NaiveDatetime
    notes: str = Field("", max_length=10000)
    cleared: bool = False
    event_id: str | None = None

@app.post("/api/containers/{cid}/actions")
def action(cid: str, model: ActionInput):
    with database() as db:
        activity_before = activity_cleanup.snapshot(db)
        c = get_container(db, cid)
        if model.action == 'third_instar' and c['kind'] not in ('vial', 'bottle'):
            raise HTTPException(409, 'third_instar_culture_required')
        if c['kind'] == 'petri_dish' and model.action in ('remove', 'clear', 'collect', 'tissue'):
            raise HTTPException(409, 'use_egg_workflow')
        at = model.at.replace(tzinfo=None)
        if (at < start_of(c) and model.action != "activate") or at > now_of(db) + timedelta(minutes=1):
            raise HTTPException(422, "invalid_action_time")
        if c['kind'] == 'egg_laying' and model.action == 'activate' and at > now_of(db):
            raise HTTPException(422, 'invalid_action_time')
        if c["status"] not in ("active", "planned"):
            raise HTTPException(409, "container_inactive")
        if c["status"] == "planned" and model.action != "activate":
            raise HTTPException(409, "activate_first")
        if model.action == "activate" and c["status"] != "planned":
            raise HTTPException(409, "container_already_active")
        stamp = at.isoformat(timespec="minutes")
        if model.action in ("cold", "warm"):
            temps = temperatures_of(db, cid)
            if temps and stamp <= temps[-1]["at"]:
                raise HTTPException(422, "temperature_time_order")
            if c["temperature_policy"] == "forbidden" and model.action == "cold":
                raise HTTPException(409, "temperature_forbidden")
            db.execute("INSERT INTO temperatures VALUES(?,?,?,?)", (uid(), cid, stamp, 18 if model.action == "cold" else 25))
        elif model.action == "remove":
            if c["parents"] != "present":
                raise HTTPException(409, "parents_absent")
            c["parents"] = "removed"
        elif model.action in ("larvae", "pupae", "eclosion", 'first_instar'):
            c["stage"] = model.action
            if model.action == 'eclosion':
                c['first_eclosion_at'] = min(stamp, c.get('first_eclosion_at') or stamp)
        elif model.action in ("complete", "discard"):
            c["status"] = "completed" if model.action == "complete" else "discarded"
        elif model.action == "activate":
            if c['kind'] == 'petri_dish' and at < parse(c['incubation']['lay_end']):
                raise HTTPException(422, 'egg_window_after_setup')
            if c['kind'] == 'egg_laying':
                if not c.get('genotype', '').strip():
                    raise HTTPException(409, 'egg_genotype_review_required')
                if c.get('source_id'):
                    source = get_container(db, c['source_id'])
                    if source['status'] != 'active':
                        raise HTTPException(409, 'container_inactive')
                    if at < start_of(source):
                        raise HTTPException(422, 'invalid_action_time')
                    if c.get('adult_source') == 'parents':
                        c.update(cohort_id=source['cohort_id'], transfer_index=source['transfer_index'] + 1)
                    if c.get('inherit_source_temperature', False):
                        c['initial_temperature'] = temperature_at(db, source, at)
                    if c.get('adult_source') in ('parents', 'offspring'):
                        log(db, source['id'], 'egg_laying_' + c['adult_source'], stamp, c['label'])
                c.update(genotype_review_required=False, setup_time_review_required=False)
            c["status"] = "active"
            c["setup_date"], c["setup_time"] = at.date().isoformat(), at.strftime("%H:%M")
        if model.action == "clear" or (model.cleared and model.action != 'third_instar'):
            if c["parents"] == "present":
                c["parents"] = "removed"
            if model.action != "clear":
                log(db, cid, "clear", stamp)
        log(db, cid, model.action, stamp, model.notes)
        save_container(db, c)
        if model.event_id:
            row = db.execute("SELECT payload FROM events WHERE id=? AND container_id=?", (model.event_id, cid)).fetchone()
            if not row:
                raise HTTPException(404, "event_not_found")
            e = json.loads(row[0])
            if e["status"] != "pending" or {'watch': 'eclosion', 'egg_setup': 'activate'}.get(e['kind'], e['kind']) != model.action:
                raise HTTPException(409, "event_action_mismatch")
            e["status"] = "done"
            save_event(db, e)
        else:
            # Details-page operations and task completion share the same stored work.
            matches = []
            for row in db.execute('SELECT payload FROM events WHERE container_id=?', (cid,)).fetchall():
                e = json.loads(row[0])
                if e['status'] != 'pending' or {'watch': 'eclosion', 'egg_setup': 'activate'}.get(e['kind'], e['kind']) != model.action:
                    continue
                if model.action in ('collect', 'score') and not (parse(e['due']) <= at <= parse(e['end'])):
                    continue
                if model.action in ('tissue', 'cold', 'warm', 'collect', 'first_instar', 'remove', 'eclosion', 'score', 'activate', 'third_instar'):
                    matches.append(e)
            if matches:
                e = min(matches, key=lambda x: abs((parse(x['due']) - at).total_seconds()))
                e['status'] = 'done'
                save_event(db, e)
        if c["status"] in ("completed", "discarded"):
            for row in db.execute('SELECT payload FROM egg_batches WHERE source_id=?', (cid,)).fetchall():
                batch = json.loads(row[0])
                if batch['status'] == 'planned':
                    batch['status'] = 'cancelled'
                    save_egg_batch(db, batch)
            for row in db.execute("SELECT payload FROM events WHERE container_id=?", (cid,)).fetchall():
                e = json.loads(row[0])
                if e["status"] == "pending":
                    e["status"] = "cancelled"
                    e['cancel_reason'] = 'container_closed'
                    save_event(db, e)
        reconcile(db, c)
        activity_cleanup.record(db, activity_before, cid)
        return c

class EventInput(BaseModel):
    container_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    due: NaiveDatetime
    end: NaiveDatetime
    critical: bool = False
    egg_batch_id: str | None = None

    @model_validator(mode="after")
    def order(self):
        if self.end < self.due:
            raise ValueError("invalid_window")
        return self

@app.post("/api/events")
def add_event(model: EventInput):
    with database() as db:
        if model.egg_batch_id:
            batch = get_egg_batch(db, model.egg_batch_id)
            if batch['status'] == 'cancelled' or model.container_id != batch['source_id']:
                raise HTTPException(409, 'invalid_egg_source')
        if model.container_id:
            if get_container(db, model.container_id)['status'] not in ('active', 'planned'):
                raise HTTPException(409, 'container_inactive')
        event = {**model.model_dump(mode="json"), "id": uid(), "rule_key": "custom-" + uid(), "kind": "custom", "basis": "manual", "status": "pending", "pinned": True}
        save_event(db, event)
        return event

class EventUpdate(BaseModel):
    status: Literal["pending", "done", "skipped", "disabled"] | None = None
    due: NaiveDatetime | None = None
    end: NaiveDatetime | None = None
    restore: bool = False

@app.patch("/api/events/{eid}")
def update_event(eid: str, model: EventUpdate):
    with database() as db:
        row = db.execute("SELECT payload FROM events WHERE id=?", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "event_not_found")
        e = json.loads(row[0])
        if e['kind'] == 'egg_setup' and model.status == 'done':
            raise HTTPException(409, 'egg_setup_activation_required')
        if e["container_id"] and (model.restore or model.status == "pending") and get_container(db, e["container_id"])["status"] in ("completed", "discarded"):
            raise HTTPException(409, "container_inactive")
        if model.status:
            e["status"] = model.status
        if model.due:
            length = parse(e["end"]) - parse(e["due"])
            e.update(due=model.due.isoformat(timespec="minutes"), end=(model.end or model.due + length).isoformat(timespec="minutes"), pinned=True)
        elif model.end:
            e.update(end=model.end.isoformat(timespec='minutes'), pinned=True)
        if model.restore:
            e.update(pinned=False, status="pending")
        if parse(e["end"]) < parse(e["due"]):
            raise HTTPException(422, "invalid_window")
        save_event(db, e)
        if e["container_id"]:
            reconcile(db, get_container(db, e["container_id"]))
        return json.loads(db.execute("SELECT payload FROM events WHERE id=?", (eid,)).fetchone()[0])

class AvailabilityInput(BaseModel):
    date: date
    kind: Literal["workday", "rest", "holiday", "leave", "blocked", "partial"]
    windows: list[list[str]] = Field(default_factory=list)
    notes: str = Field("", max_length=1000)
    _windows = field_validator("windows")(validate_windows)

@app.put("/api/availability")
def put_availability(model: AvailabilityInput):
    with database() as db:
        value = model.model_dump(mode="json")
        if value["kind"] in ("rest", "holiday", "leave", "blocked"):
            value["windows"] = []
        db.execute("INSERT INTO availability VALUES(?,?) ON CONFLICT(date) DO UPDATE SET payload=excluded.payload", (value["date"], dump(value)))
        return value

@app.delete("/api/availability/{day}")
def delete_availability(day: date):
    with database() as db:
        db.execute("DELETE FROM availability WHERE date=?", (day.isoformat(),))
    return {"ok": True}

class SettingsInput(BaseModel):
    locale: str = Field("en", pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$", max_length=35)
    timezone: str = "Asia/Shanghai"
    weekly: dict[str, list[list[str]]]
    template: Template

    @field_validator("weekly")
    @classmethod
    def valid_weekly(cls, value):
        if set(value) != {str(i) for i in range(7)}:
            raise ValueError("invalid_weekly")
        for windows in value.values():
            validate_windows(windows)
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError("invalid_timezone")
        return value

@app.put("/api/settings")
def put_settings(model: SettingsInput):
    with database() as db:
        previous = settings_of(db)
        if model.timezone != previous["timezone"] and db.execute("SELECT COUNT(*) FROM containers").fetchone()[0]:
            raise HTTPException(409, "timezone_locked")
        db.execute("UPDATE meta SET value=? WHERE key='settings'", (dump(model.model_dump(mode="json")),))
    return {"ok": True}

@app.get("/api/containers/{cid}/suggestions")
def suggestions(cid: str):
    with database() as db:
        c = get_container(db, cid)
        reconcile(db, c)
        exceptions = [json.loads(x[0]) for x in db.execute("SELECT payload FROM availability")]
        # A pinned critical event cannot be treated as a movable developmental event.
        if any(json.loads(x[0]).get("pinned") and json.loads(x[0])["critical"] and json.loads(x[0])["status"] == "pending" for x in db.execute("SELECT payload FROM events WHERE container_id=?", (cid,))):
            return {"state": "pinned_critical", "options": []}
        excluded = [e['rule_key'] for e in (json.loads(x[0]) for x in db.execute('SELECT payload FROM events WHERE container_id=?', (cid,))) if e['status'] != 'pending']
        return suggest_cooling(c, temperatures_of(db, cid), settings_of(db), exceptions, now_of(db), excluded)

class PlanInput(BaseModel):
    cold_at: NaiveDatetime
    warm_at: NaiveDatetime

class SetupPlanInput(BaseModel):
    setup_at: NaiveDatetime

@app.post("/api/containers/{cid}/setup-plan")
def accept_setup_plan(cid: str, model: SetupPlanInput):
    result = suggestions(cid)
    stamp = model.setup_at.isoformat(timespec="minutes")
    if result["state"] != "setup_suggested" or not any(x["setup_at"] == stamp for x in result["options"]):
        raise HTTPException(409, "plan_stale")
    with database() as db:
        c = get_container(db, cid)
        if c["status"] != "planned":
            raise HTTPException(409, "container_already_active")
        c.update(setup_date=stamp[:10], setup_time=stamp[11:16])
        save_container(db, c)
        log(db, cid, "setup_planned", now_of(db).isoformat(timespec="minutes"), stamp)
        reconcile(db, c)
        return c

@app.post("/api/containers/{cid}/plans")
def accept_plan(cid: str, model: PlanInput):
    result = suggestions(cid)
    cold, warm = model.cold_at.isoformat(timespec="minutes"), model.warm_at.isoformat(timespec="minutes")
    option = next((x for x in result["options"] if x.get("cold_at") == cold and x.get("warm_at") == warm), None)
    if not option:
        raise HTTPException(409, "plan_stale")
    with database() as db:
        if any(json.loads(x[0])["status"] == "pending" and json.loads(x[0])["rule_key"].startswith("plan-") for x in db.execute("SELECT payload FROM events WHERE container_id=?", (cid,))):
            raise HTTPException(409, "plan_exists")
        pid = uid()
        plan = {"id": pid, "container_id": cid, **option}
        db.execute("INSERT INTO plans VALUES(?,?,?)", (pid, cid, dump(plan)))
        for kind, at in [("cold", cold), ("warm", warm)]:
            save_event(db, {"id": uid(), "container_id": cid, "rule_key": f"plan-{pid}-{kind}", "kind": kind,
                            "due": at, "end": (parse(at) + timedelta(minutes=15)).isoformat(timespec="minutes"),
                            "title": "", "critical": True, "basis": "manual", "status": "pending", "pinned": True})
        return plan

@app.get("/api/backup")
def backup():
    folder = ROOT / "backups"
    folder.mkdir(exist_ok=True)
    target = folder / f"flykeeper-{datetime.now():%Y%m%d-%H%M%S}-{uid()[:4]}.db"
    source = sqlite3.connect(DB_PATH)
    dest = sqlite3.connect(target)
    try:
        source.backup(dest)
    finally:
        source.close()
        dest.close()
    return FileResponse(target, media_type="application/vnd.sqlite3", filename=target.name)

def get_egg_batch(db, bid):
    row = db.execute('SELECT payload FROM egg_batches WHERE id=?', (bid,)).fetchone()
    if not row:
        raise HTTPException(404, 'egg_batch_not_found')
    return json.loads(row[0])

def save_egg_batch(db, value):
    db.execute('INSERT INTO egg_batches VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload', (value['id'], value['source_id'], dump(value)))

class EggBatchInput(BaseModel):
    label: str = Field(min_length=1, max_length=80)
    lay_start: NaiveDatetime
    lay_end: NaiveDatetime
    genotype: str = Field(min_length=1, max_length=1000)
    temperature: Literal[18, 25] = 25
    notes: str = Field('', max_length=10000)

    @model_validator(mode='after')
    def order(self):
        if self.lay_end < self.lay_start or not self.label.strip() or not self.genotype.strip():
            raise ValueError('invalid_egg_window')
        return self

@app.post('/api/containers/{cid}/egg-batches')
def new_egg_batch(cid: str, model: EggBatchInput):
    with database() as db:
        activity_before = activity_cleanup.snapshot(db)
        c = get_container(db, cid)
        if c['kind'] != 'egg_laying' or c['status'] != 'active' or c['parents'] != 'present':
            raise HTTPException(409, 'egg_laying_unavailable')
        if not c.get('genotype', '').strip():
            raise HTTPException(409, 'egg_genotype_review_required')
        if not c.get('setup_time'):
            raise HTTPException(409, 'egg_setup_time_required')
        if model.lay_start < start_of(c):
            raise HTTPException(422, 'invalid_egg_window')
        batch = {**model.model_dump(mode='json'), 'id':uid(), 'source_id':cid, 'status':'planned', 'collected_at':None, 'uses':[]}
        save_egg_batch(db, batch)
        due = model.lay_end.isoformat(timespec='minutes')
        save_event(db, {'id':uid(), 'container_id':cid, 'rule_key':f"custom-eggs-{batch['id']}", 'egg_batch_id':batch['id'], 'batch_label':batch['label'], 'kind':'egg_collect', 'due':due, 'end':due, 'critical':True, 'basis':'hours', 'title':'', 'status':'pending', 'pinned':True})
        log(db, cid, 'egg_window', now_of(db).isoformat(timespec='minutes'), batch['label'])
        activity_cleanup.record(db, activity_before, cid)
        return batch

class EggBatchAction(BaseModel):
    action: Literal['collect', 'use', 'cancel']
    at: NaiveDatetime
    purpose: Literal['dissection', 'imaging', 'other'] = 'other'
    notes: str = Field('', max_length=10000)

@app.post('/api/egg-batches/{bid}/actions')
def egg_batch_action(bid: str, model: EggBatchAction):
    with database() as db:
        activity_before = activity_cleanup.snapshot(db)
        batch = get_egg_batch(db, bid)
        if model.at > now_of(db) or model.at < parse(batch['lay_start']):
            raise HTTPException(422, 'invalid_action_time')
        if batch['status'] == 'cancelled':
            raise HTTPException(409, 'egg_batch_cancelled')
        if model.action == 'collect':
            source = get_container(db, batch['source_id'])
            if batch['status'] != 'planned' or model.at < parse(batch['lay_end']) or source['status'] != 'active':
                raise HTTPException(409, 'egg_collection_unavailable')
            batch.update(status='collected', collected_at=model.at.isoformat(timespec='minutes'))
        elif model.action == 'use':
            if batch['status'] != 'collected' or model.at < parse(batch['collected_at']):
                raise HTTPException(409, 'eggs_not_collected')
            batch['uses'].append({'id':uid(), 'at':model.at.isoformat(timespec='minutes'), 'purpose':model.purpose, 'notes':model.notes})
        else:
            batch['status'] = 'cancelled'
        save_egg_batch(db, batch)
        log(db, batch['source_id'], 'egg_' + model.action, model.at.isoformat(timespec='minutes'), batch['label'] + (': ' + model.notes if model.notes else ''))
        for row in db.execute('SELECT payload FROM events WHERE container_id=?', (batch['source_id'],)).fetchall():
            event = json.loads(row[0])
            if event.get('egg_batch_id') == bid and event['status'] == 'pending':
                if model.action == 'cancel' or (event['kind'] == 'egg_collect' and model.action == 'collect'):
                    event['status'] = 'cancelled' if model.action == 'cancel' else 'done'
                    save_event(db, event)
        activity_cleanup.record(db, activity_before, batch['source_id'])
        return batch

from . import ai_assistant, ai_models, workspace_restore

ai_assistant.install_routes(app, sys.modules[__name__])
ai_models.install_routes(app, sys.modules[__name__])
app.include_router(workspace_restore.make_router(sys.modules[__name__]))

FRONTEND = ROOT / "frontend" / "dist" / "local"
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
