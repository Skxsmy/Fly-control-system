"""Researcher-defined injection preparation; planned housing and actual handling."""
import json
from datetime import datetime, time, timedelta
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, NaiveDatetime, field_serializer, field_validator

from . import activity_cleanup
from .timing import calendar_day_target, elapsed_target


class InjectionState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['source', 'conditioning', 'cage']
    phase: Literal['collecting', 'awaiting_flies', 'conditioning', 'awaiting_transfer', 'renew', 'embryos', 'finished']
    initiated_at: NaiveDatetime
    started_at: NaiveDatetime | None = None
    transferred_at: NaiveDatetime | None = None
    female_count: int | None = Field(None, ge=0, le=1000000)
    male_count: int | None = Field(None, ge=0, le=1000000)
    female_target: Literal[200] = 200
    male_target: Literal[50] = 50
    cycle: int = Field(0, ge=0, le=1000000)
    renewed_at: NaiveDatetime | None = None
    next_renew_at: NaiveDatetime | None = None
    finished_at: NaiveDatetime | None = None

    @field_serializer('initiated_at', 'started_at', 'transferred_at', 'renewed_at', 'next_renew_at', 'finished_at')
    def minute_stamp(self, value):
        return value.isoformat(timespec='minutes') if value is not None else None


class PreparationInput(BaseModel):
    at: NaiveDatetime
    genotype: str = Field(min_length=1, max_length=1000)
    notes: str = Field('', max_length=10000)

    @field_validator('genotype')
    @classmethod
    def known_genotype(cls, value):
        if not value.strip():
            raise ValueError('genotype_required')
        return value.strip()


class InjectionAction(BaseModel):
    action: Literal['injection_collect', 'injection_transfer', 'injection_renew', 'injection_embryos']
    at: NaiveDatetime
    event_id: str | None = None
    female_count: int | None = Field(None, ge=0, le=1000000, strict=True)
    male_count: int | None = Field(None, ge=0, le=1000000, strict=True)
    continue_collection: bool | None = None
    notes: str = Field('', max_length=10000)


def generated_events(container, temperatures):
    """Source developmental targets; adult handling uses the actual collection D0."""
    from .domain import forecast, generated_events as ordinary_events, parse
    state = container['injection']
    events = []

    def add(key, kind, due, end=None, basis='hours', all_day=False):
        events.append({'rule_key': key, 'kind': kind, 'due': due.isoformat(timespec='minutes'),
                       'end': (end or due).isoformat(timespec='minutes'), 'critical': True,
                       'basis': basis, 'title': '', 'all_day': all_day})

    def add_handling_day(key, kind, day):
        anchor = parse(state['started_at'])
        due = calendar_day_target(anchor, day)
        add(key, kind, due, due.replace(hour=23, minute=59), 'calendar', True)
        # Retain the original elapsed-time reference while opening the day's
        # handling task at midnight. Actual handling is always recorded separately.
        events[-1]['scheduled_at'] = elapsed_target(anchor, timedelta(days=day)).isoformat(timespec='minutes')

    if state['role'] == 'source':
        ordinary = {key: value for key, value in container.items() if key != 'injection'}
        # Handling/checks remain; the source's harvesting outcome is now this chain.
        events = [e for e in ordinary_events(ordinary, temperatures)
                  if e['kind'] in ('transfer', 'remove', 'check', 'tissue', 'watch')]
        if state['phase'] == 'collecting':
            for day in range(10, 13):
                target = forecast(container, temperatures, day).date()
                add(f'injection-collect-{day}', 'injection_collect', datetime.combine(target, time.min),
                    datetime.combine(target, time(23, 59)), 'development', True)
    elif state['role'] == 'conditioning' and state['phase'] == 'conditioning':
        add_handling_day('injection-transfer', 'injection_transfer', 4)
    elif state['role'] == 'cage':
        if state['phase'] == 'renew':
            add_handling_day(f'injection-renew-{state["cycle"]}', 'injection_renew', 5)
        elif state['phase'] == 'embryos':
            add(f'injection-embryos-{state["cycle"]}', 'injection_embryos',
                elapsed_target(parse(state['renewed_at']), timedelta(minutes=30)))
    return events


def _child(db, parent_id, role):
    matches = [value for row in db.execute('SELECT payload FROM containers')
               if (value := json.loads(row[0])).get('source_id') == parent_id
               and (value.get('injection') or {}).get('role') == role]
    if len(matches) > 1:
        raise HTTPException(409, 'injection_link_conflict')
    return matches[0] if matches else None


def _new_housing(db, api, parent, role, at, state):
    kind = 'bottle' if role == 'conditioning' else 'cage'
    value = api.ContainerInput(kind=kind, purpose='injection', genotype=parent['genotype'],
        setup_date=at.date(), setup_time=at.strftime('%H:%M'), initial_status='planned',
        temperature_policy='forbidden', template=parent['template'], injection=state,
        workflow=api.Workflow(transfer_enabled=False), notes='').model_dump(mode='json')
    value.pop('initial_status')
    value.update(id=api.uid(), label=api.next_container_label(db, kind, namespace='injection' if kind == 'bottle' else None),
                 source_id=parent['id'], cohort_id=parent['cohort_id'] if role == 'cage' else api.uid(),
                 status='planned', parents='present', stage='unobserved', transfer_index=0,
                 source_relation='injection_preparation' if role == 'conditioning' else 'injection_cage')
    api.save_container(db, value)
    api.log(db, value['id'], 'created', api.now_of(db).isoformat(timespec='minutes'))
    api.reconcile(db, value)
    return value


def _ensure_cage(db, api, bottle):
    cage = _child(db, bottle['id'], 'cage')
    if cage:
        return cage
    state = {**bottle['injection'], 'role': 'cage', 'phase': 'awaiting_transfer'}
    return _new_housing(db, api, bottle, 'cage', api.parse(state['started_at']), state)


def refresh_due(db, api):
    """Materialize a planned cage on D4; never record an automatic transfer."""
    for row in db.execute('SELECT payload FROM containers').fetchall():
        bottle = json.loads(row[0])
        state = bottle.get('injection') or {}
        if (bottle['status'] == 'active' and state.get('role') == 'conditioning'
                and state.get('phase') == 'conditioning'
                and api.now_of(db) >= calendar_day_target(api.parse(state['started_at']), 4)):
            _ensure_cage(db, api, bottle)


def close_pending_housing(db, api, container, at):
    """Closing upstream work cancels an untouched housing plan, never live flies."""
    role = (container.get('injection') or {}).get('role')
    child_role = {'source': 'conditioning', 'conditioning': 'cage'}.get(role)
    if child_role is None:
        return
    child = _child(db, container['id'], child_role)
    phase = {'conditioning': 'awaiting_flies', 'cage': 'awaiting_transfer'}[child_role]
    if not child or child['status'] != 'planned' or child['injection']['phase'] != phase:
        return
    child['status'] = 'discarded'
    child['injection'].update(phase='finished', finished_at=at)
    api.save_container(db, child)
    api.log(db, child['id'], 'injection_plan_cancelled', at)
    api.reconcile(db, child)


def _event(db, api, container, model):
    api.reconcile(db, container)
    if model.action in ('injection_renew', 'injection_embryos') and not model.event_id:
        raise HTTPException(422, 'injection_event_required')
    events = [json.loads(row[0]) for row in db.execute('SELECT payload FROM events WHERE container_id=?', (container['id'],))]
    current_keys = {e['rule_key'] for e in generated_events(container, api.temperatures_of(db, container['id']))}
    eligible = [e for e in events if e['kind'] == model.action and e['status'] == 'pending' and e['rule_key'] in current_keys]
    if model.event_id:
        chosen = next((e for e in eligible if e['id'] == model.event_id), None)
        if chosen is None:
            raise HTTPException(409, 'injection_event_stale')
        return chosen
    if not eligible:
        raise HTTPException(409, 'injection_action_unavailable')
    # A direct operation defaults to the current day's slot, then the closest slot.
    stamp = model.at.isoformat(timespec='minutes')
    return min(eligible, key=lambda e: (not e['due'] <= stamp <= e['end'], abs((api.parse(e['due']) - model.at).total_seconds())))


def install_routes(app, api):
    @app.post('/api/containers/{cid}/injection-preparation')
    def prepare(cid: str, model: PreparationInput):
        with api.database() as db:
            source = api.get_container(db, cid)
            if source['kind'] not in ('vial', 'bottle') or source.get('injection'):
                raise HTTPException(409, 'injection_source_required')
            if source['status'] != 'active':
                raise HTTPException(409, 'container_inactive')
            if model.at < api.start_of(source) or model.at > api.now_of(db):
                raise HTTPException(422, 'invalid_action_time')
            if (api.temperature_at(db, source, model.at) != 25
                    or api.temperature_at(db, source, api.now_of(db)) != 25):
                raise HTTPException(409, 'injection_warm_source_first')
            if any(item['temperature'] == 18 and api.parse(item['at']) > model.at
                   for item in api.temperatures_of(db, cid)):
                raise HTTPException(422, 'invalid_action_time')
            before = activity_cleanup.snapshot(db)
            stamp = model.at.isoformat(timespec='minutes')
            metadata = InjectionState(role='source', phase='collecting', initiated_at=model.at).model_dump(mode='json')
            source['injection'] = metadata
            source['temperature_policy'] = 'forbidden'
            api.save_container(db, source)
            # The collected genotype is verified input, never the cross's target.
            parent = {**source, 'genotype': model.genotype}
            bottle = _new_housing(db, api, parent, 'conditioning', model.at,
                                  {**metadata, 'role': 'conditioning', 'phase': 'awaiting_flies'})
            api.log(db, cid, 'injection_preparation', stamp, model.notes)
            for row in db.execute('SELECT payload FROM events WHERE container_id=?', (cid,)).fetchall():
                event = json.loads(row[0])
                if event['kind'] in ('cold', 'warm') and event['status'] == 'pending':
                    event.update(status='cancelled', cancel_reason='injection_preparation')
                    api.save_event(db, event)
            api.reconcile(db, source)
            activity_cleanup.record(db, before, cid)
            return {'source': source, 'bottle': bottle}

    @app.post('/api/containers/{cid}/injection-actions')
    def perform(cid: str, model: InjectionAction):
        with api.database() as db:
            c = api.get_container(db, cid)
            state = c.get('injection') or {}
            expected = {'injection_collect': ('source', 'collecting'),
                        'injection_transfer': ('conditioning', 'conditioning'),
                        'injection_renew': ('cage', 'renew'),
                        'injection_embryos': ('cage', 'embryos')}[model.action]
            if (state.get('role'), state.get('phase')) != expected or c['status'] != 'active':
                raise HTTPException(409, 'injection_action_unavailable')
            predecessor = state.get('renewed_at') or state.get('transferred_at') or state.get('started_at') or state['initiated_at']
            if model.at < api.parse(predecessor) or model.at > api.now_of(db):
                raise HTTPException(422, 'invalid_action_time')
            event = _event(db, api, c, model)
            before = activity_cleanup.snapshot(db)
            stamp = model.at.isoformat(timespec='minutes')
            result = {'container': c}
            if model.action == 'injection_collect':
                if model.female_count is None or model.male_count is None:
                    raise HTTPException(422, 'injection_counts_required')
                bottle = _child(db, cid, 'conditioning')
                if not bottle or bottle['status'] != 'planned' or bottle['injection']['phase'] != 'awaiting_flies':
                    raise HTTPException(409, 'injection_link_conflict')
                counts = {'female_count': model.female_count, 'male_count': model.male_count, 'started_at': stamp}
                state.update(**counts, phase='finished', finished_at=stamp)
                bottle['injection'].update(**counts, phase='conditioning')
                bottle.update(status='active', setup_date=stamp[:10], setup_time=stamp[11:16])
                api.save_container(db, bottle)
                api.log(db, bottle['id'], 'injection_flies_added', stamp, model.notes)
                api.reconcile(db, bottle)
                result['bottle'] = bottle
            elif model.action == 'injection_transfer':
                cage = _ensure_cage(db, api, c)
                if cage['status'] != 'planned' or cage['injection']['phase'] != 'awaiting_transfer':
                    raise HTTPException(409, 'injection_link_conflict')
                cage['injection'].update(phase='renew', transferred_at=stamp)
                cage.update(status='active')
                state.update(phase='finished', finished_at=stamp)
                c.update(status='discarded', parents='transferred')
                api.save_container(db, cage)
                api.log(db, cage['id'], 'injection_flies_added', stamp, model.notes)
                api.reconcile(db, cage)
                result['cage'] = cage
            elif model.action == 'injection_renew':
                state.update(phase='embryos', cycle=state['cycle'] + 1, renewed_at=stamp)
            else:
                if model.continue_collection is None:
                    raise HTTPException(422, 'injection_continue_required')
                if model.continue_collection:
                    state.update(cycle=state['cycle'] + 1, renewed_at=stamp)
                else:
                    state.update(phase='finished', finished_at=stamp)
            event['status'] = 'done'
            api.save_event(db, event)
            api.save_container(db, c)
            api.log(db, cid, model.action, stamp, model.notes)
            if model.action == 'injection_embryos' and model.continue_collection:
                api.log(db, cid, 'injection_renew', stamp, model.notes)
            api.reconcile(db, c)
            activity_cleanup.record(db, before, cid)
            return result
