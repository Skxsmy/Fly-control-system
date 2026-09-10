"""Deterministic, lab-local scheduling. Estimates are not biological guarantees."""
from datetime import date, datetime, time, timedelta

DEFAULT_TEMPLATE = {
    "transfer_day": 3, "max_transfers": 2, "check_day": 6,
    "collection_day": 10, "collection_days": 1, "stock_interval": 11,
    "windows": [["09:00", "11:00"], ["15:00", "15:30"], ["19:00", "21:00"]],
    "rate18": 0.5, "virgin_hours25": 8, "virgin_hours18": 16,
    "watch_day": 9,
}
DEFAULT_SETTINGS = {
    "locale": "en", "timezone": "Asia/Shanghai",
    "weekly": {str(i): [["09:00", "12:00"], ["14:00", "17:00"], ["19:00", "21:00"]] if i < 5 else [] for i in range(7)},
    "template": DEFAULT_TEMPLATE,
}

def parse(value):
    return datetime.fromisoformat(value)

def start_of(container):
    # Midnight is a lower bound, never represented as an observed setup time.
    return parse(container["setup_date"] + "T" + (container.get("setup_time") or "00:00"))

def rate(temp, template):
    return template["rate18"] if temp == 18 else 1.0

def effective_age(container, temperatures, at):
    origin = start_of(container)
    if at <= origin:
        return 0.0
    total, cursor, current = 0.0, origin, container.get("initial_temperature", 25)
    for segment in sorted(temperatures, key=lambda x: x["at"]):
        point = parse(segment["at"])
        if point > at:
            break
        if point > cursor:
            total += (point - cursor).total_seconds() / 86400 * rate(current, container["template"])
            cursor = point
        current = segment["temperature"]
    total += (at - cursor).total_seconds() / 86400 * rate(current, container["template"])
    return max(0.0, total)

def forecast(container, temperatures, target):
    cursor, accumulated = start_of(container), 0.0
    current = container.get("initial_temperature", 25)
    for segment in sorted(temperatures, key=lambda x: x["at"]):
        point = parse(segment["at"])
        if point <= cursor:
            current = segment["temperature"]
            continue
        progress = (point - cursor).total_seconds() / 86400 * rate(current, container["template"])
        if accumulated + progress >= target:
            return cursor + timedelta(days=(target - accumulated) / rate(current, container["template"]))
        accumulated += progress
        cursor, current = point, segment["temperature"]
    return cursor + timedelta(days=max(0, target - accumulated) / rate(current, container["template"]))

def eclosion_estimate(container, temperatures):
    """Expose an observation when available, otherwise the culture's configured estimate."""
    if container['kind'] not in ('vial', 'bottle'):
        return None
    observed = container.get('first_eclosion_at')
    return {
        'at': observed or forecast(container, temperatures, container['template']['collection_day']).isoformat(timespec='minutes'),
        'basis': 'observed' if observed else 'estimated',
        'source_planned': container['status'] == 'planned',
        'date_only': not bool(observed or container.get('setup_time')),
    }

def generated_events(container, temperatures):
    if container["status"] not in ("active", "planned"):
        return []
    template = container["template"]
    origin = start_of(container)
    events = []
    def add(key, kind, due, end=None, critical=False, basis="calendar"):
        events.append({"rule_key": key, "kind": kind, "due": due.isoformat(timespec="minutes"),
                       "end": (end or due).isoformat(timespec="minutes"), "critical": critical,
                       "basis": basis, "title": ""})
    if container['kind'] == 'egg_laying':
        if container['status'] == 'planned':
            if container.get('setup_time'):
                add('egg-setup', 'egg_setup', origin, critical=True)
            estimate = container.get('source_eclosion_estimate')
            if container.get('adult_source') == 'offspring' and estimate and estimate['basis'] == 'estimated':
                ready = parse(estimate['at'])
                if estimate.get('date_only'):
                    windows = container.get('source_collection_windows', template['windows'])
                    ready = datetime.combine(ready.date(), time.fromisoformat(windows[0][0]))
                add('offspring-ready', 'offspring_ready', ready, critical=True, basis='development')
        return events  # Each timed egg collection has its own reminder.
    if container['kind'] == 'petri_dish':
        interval = incubation_window(container, temperatures)
        add('first-instar', 'first_instar', parse(interval['start']), parse(interval['end']), True, 'hours')
        events[-1]['timing_review'] = interval['review']
        return events
    workflow = container.get('workflow')
    third_instar = container['purpose'] == 'larvae' or (
        container['purpose'] == 'cross' and workflow and workflow.get('cross_goal') == 'third_instar'
    )
    if container["parents"] == "present" and container["transfer_index"] < template["max_transfers"] and (workflow is None or workflow['transfer_enabled']):
        due = origin + timedelta(days=template["transfer_day"])
        if not container.get("setup_time"):
            due = due.replace(hour=9)
        add("transfer", "transfer", due)
    if workflow and container['purpose'] in ('cross', 'virgin', 'larvae') and container['parents'] == 'present':
        due = (origin + timedelta(days=min(template['transfer_day'], workflow['remove_day']))).replace(hour=9, minute=0)
        end = (origin + timedelta(days=workflow['remove_day'])).replace(hour=17, minute=0)
        add('parents-remove', 'remove', due, end, critical=True)
    if third_instar:
        protocol = workflow or {}
        day = origin.date() + timedelta(days=protocol.get('third_instar_day', 5))
        window = protocol.get('third_instar_window', ['09:00', '17:00'])
        due = datetime.combine(day, time.fromisoformat(window[0]))
        end = datetime.combine(day, time.fromisoformat(window[1]))
        # This is the user's provisional calendar target, not a temperature-derived stage prediction.
        add('third_instar', 'third_instar', due, end, critical=True)
        return events
    check = forecast(container, temperatures, template["check_day"]).replace(hour=9, minute=0)
    add("check", "tissue" if container["kind"] == "bottle" else "check", check, basis="development")
    if container["purpose"] == "stock":
        due = (origin + timedelta(days=template["stock_interval"])).replace(hour=9, minute=0)
        add("stock", "stock", due)
    else:
        watch = forecast(container, temperatures, template["watch_day"]).replace(hour=9, minute=0)
        add("watch", "watch", watch, critical=True, basis="development")
        scoring = container['purpose'] == 'cross' and workflow and workflow['cross_goal'] == 'score'
        first = forecast(container, temperatures, workflow['selection_day'] if scoring else template['collection_day'])
        # Virgin collection is exactly ONE configured culture day, as requested.
        if scoring and workflow['follow_eclosion'] and container.get('first_eclosion_at'):
            first = parse(container['first_eclosion_at'])
        if scoring:
            for day in range(workflow['selection_days']):
                due = datetime.combine(first.date() + timedelta(days=day), time.fromisoformat(workflow['selection_window'][0]))
                end = datetime.combine(due.date(), time.fromisoformat(workflow['selection_window'][1]))
                add(f'score-{day}', 'score', due, end, True, 'development')
            return events
        for day in range(1):
            for slot, window in enumerate(template["windows"]):
                due = datetime.combine(first.date() + timedelta(days=day), time.fromisoformat(window[0]))
                end = datetime.combine(due.date(), time.fromisoformat(window[1]))
                add(f"collect-{day}-{window[0]}-{window[1]}", "collect", due, end, True, "development")
    return events

def incubation_window(container, temperatures):
    p = container['incubation']
    # The first and last eggs have different ages; transfer never resets egg age.
    earliest = parse(p['lay_start']) + timedelta(hours=p['min_hours'])
    latest = parse(p['lay_end']) + timedelta(hours=p['max_hours'])
    reference = p['reference_temperature']
    review = container['initial_temperature'] != reference or p.get('lay_temperature', reference) != reference or any(t['temperature'] != reference for t in temperatures)
    return {'start': earliest.isoformat(timespec='minutes'), 'end': latest.isoformat(timespec='minutes'), 'review': review}

def available_windows(day, settings, exceptions):
    override = next((x for x in exceptions if x["date"] == day.isoformat()), None)
    windows = override["windows"] if override else settings["weekly"].get(str(day.weekday()), [])
    return [(datetime.combine(day, time.fromisoformat(a)), datetime.combine(day, time.fromisoformat(b))) for a, b in windows]

def available(at, settings, exceptions, duration=15):
    return any(a <= at and at + timedelta(minutes=duration) <= b for a, b in available_windows(at.date(), settings, exceptions))

def event_conflict(event, settings, exceptions):
    start, end = parse(event["due"]), parse(event["end"])
    if end <= start:
        end = start + timedelta(minutes=15)
    # A task requires a contiguous 15-minute slot within both windows.
    day = start.date()
    while day <= end.date():
        if any(max(start, a) + timedelta(minutes=15) <= min(end, b) for a, b in available_windows(day, settings, exceptions)):
            return False
        day += timedelta(days=1)
    return True

def virgin_clock(container, temperatures, logs, now):
    clears = [x for x in logs if x["action"] == "clear" and parse(x['at']) <= now]
    if not clears:
        return {"state": "unknown", "last_clear": None, "deadline": None}
    last = max(clears, key=lambda x: x["at"])["at"]
    previous = [x for x in temperatures if x["at"] <= last]
    temp = previous[-1]["temperature"] if previous else container.get("initial_temperature", 25)
    # Mixed-temperature adult maturation has no validated linear conversion here.
    changed = any(last < x["at"] <= now.isoformat() and x["temperature"] != temp for x in temperatures)
    hours = container["template"]["virgin_hours18" if temp == 18 else "virgin_hours25"]
    deadline = parse(last) + timedelta(hours=hours)
    return {"state": "mixed" if changed else ("elapsed" if now >= deadline else "within"),
            "last_clear": last, "deadline": None if changed else deadline.isoformat(timespec="minutes")}

def suggest_cooling(container, temperatures, settings, exceptions, now, excluded_keys=None):
    if container['kind'] in ('petri_dish', 'egg_laying'):
        return {'state': 'hourly_manual', 'options': []}
    excluded_keys = set(excluded_keys or [])
    def relevant(events):
        return [e for e in events if e['rule_key'] not in excluded_keys]
    if container["status"] == "planned":
        options = []
        original = start_of(container)
        if original >= now and available(original, settings, exceptions):
            required = [e for e in relevant(generated_events(container, [])) if e['critical'] or e['kind'] == 'stock']
            if all(not event_conflict(e, settings, exceptions) for e in required):
                options.append({'setup_at': original.isoformat(timespec='minutes'), 'shift_hours': 0, 'events': required})
        for offset in range(15):
            day = now.date() + timedelta(days=offset)
            for a, b in available_windows(day, settings, exceptions):
                at = max(a, now)
                if at + timedelta(minutes=15) > b:
                    continue
                proposed = {**container, "setup_date": at.date().isoformat(), "setup_time": at.strftime("%H:%M")}
                events = relevant(generated_events(proposed, []))
                required = [e for e in events if e["critical"] or e["kind"] == "stock"]
                if all(not event_conflict(e, settings, exceptions) for e in required):
                    if not any(x['setup_at'] == at.isoformat(timespec='minutes') for x in options):
                        options.append({"setup_at": at.isoformat(timespec="minutes"), "shift_hours": abs((at - original).total_seconds() / 3600), "events": required})
                    break
        options.sort(key=lambda x: (x["shift_hours"], x["setup_at"]))
        return {"state": "setup_suggested" if options else "no_solution", "options": options[:3]}
    if container["temperature_policy"] == "forbidden":
        return {"state": "forbidden", "options": []}
    if container["status"] != "active":
        return {"state": "not_active", "options": []}
    if (temperatures[-1]["temperature"] if temperatures else container.get("initial_temperature", 25)) != 25:
        return {"state": "already_cold", "options": []}
    base = relevant(generated_events(container, temperatures))
    critical = [x for x in base if x["critical"] and parse(x["end"]) >= now]
    if not any(event_conflict(x, settings, exceptions) for x in critical):
        return {"state": "clear", "options": []}
    first = forecast(container, temperatures, container["template"]["watch_day"])
    if first <= now:
        return {"state": "watch_started", "options": []}
    candidates = []
    # Bounded search: hourly handling slots, one cold interval, at most 7 days cold.
    slots = []
    for offset in range(15):
        day = now.date() + timedelta(days=offset)
        for a, b in available_windows(day, settings, exceptions):
            cursor = a
            while cursor + timedelta(minutes=15) <= b:
                if cursor >= now:
                    slots.append(cursor)
                cursor += timedelta(hours=1)
    for cold in slots:
        if cold >= first:
            continue
        for warm in slots:
            hours = (warm - cold).total_seconds() / 3600
            if hours <= 0 or hours > 168:
                continue
            projected = temperatures + [{"at": cold.isoformat(), "temperature": 18}, {"at": warm.isoformat(), "temperature": 25}]
            events = relevant(generated_events(container, projected))
            future = [e for e in events if e["critical"] and parse(e["end"]) >= now]
            if not future or any(event_conflict(e, settings, exceptions) for e in future):
                continue
            watch = forecast(container, projected, container["template"]["watch_day"])
            # Guard the uncertain onset date as well as the collection slots.
            if not available_windows(watch.date(), settings, exceptions):
                continue
            candidates.append({"cold_at": cold.isoformat(timespec="minutes"), "warm_at": warm.isoformat(timespec="minutes"),
                               "hours": hours, "collection_date": forecast(container, projected, container["template"]["collection_day"]).date().isoformat(),
                               "events": future})
    candidates.sort(key=lambda x: (x["hours"], x["cold_at"]))
    return {"state": "suggested" if candidates else "no_solution", "options": candidates[:3], "resolution_minutes": 60}
