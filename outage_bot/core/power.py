from datetime import date, datetime, time, timedelta

from outage_bot.core.models import KYIV, DaySchedule, GroupSchedule

STATUS_TEXT = {
    "schedule": "действует график",
    "no_outages": "отключений не запланировано",
    "waiting": "график ещё не опубликован",
    "emergency": "АВАРИЙНЫЕ ОТКЛЮЧЕНИЯ — график не действует",
    "unknown": "оператор не публиковал график на эту дату (обычно это значит, что отключений нет, но подтверждения нет)",
}


def _at(d: date, minutes: int) -> datetime:
    return datetime.combine(d, time(), tzinfo=KYIV) + timedelta(minutes=minutes)


def merged_intervals(day: DaySchedule) -> list[tuple[int, int, str]]:
    """Сливает соседние слоты одного типа: 08:00-08:30 + 08:30-09:00 -> 08:00-09:00."""
    out: list[list] = []
    for s in sorted(day.slots, key=lambda s: s.start):
        if out and out[-1][2] == s.kind and s.start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], s.end)
        else:
            out.append([s.start, s.end, s.kind])
    return [tuple(x) for x in out]


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def day_summary(day: DaySchedule) -> dict:
    return {
        "date": day.date.isoformat(),
        "status": STATUS_TEXT[day.status],
        "no_power": [
            f"{hhmm(a)}–{hhmm(b)}" + (" (возможно)" if kind == "possible" else "") for a, b, kind in merged_intervals(day)
        ],
    }


def power_now(schedule: GroupSchedule, now: datetime) -> dict:
    """Есть ли свет сейчас и когда ближайшее отключение/включение по графику."""
    now = now.astimezone(KYIV)
    days = {d.date: d for d in schedule.days}
    today = days.get(now.date())
    if today is None or today.status in ("unknown", "waiting"):
        return {"power": "неизвестно", "reason": STATUS_TEXT[today.status] if today else "нет данных на сегодня"}
    if today.status == "emergency":
        return {"power": "возможно нет", "reason": STATUS_TEXT["emergency"]}

    events = []
    for d in sorted(days):
        if days[d].status != "schedule":
            continue
        for a, b, kind in merged_intervals(days[d]):
            start, end = _at(d, a), _at(d, b)
            if events and events[-1][1] == start and events[-1][2] == kind:
                events[-1] = (events[-1][0], end, kind)
            else:
                events.append((start, end, kind))

    current = next((e for e in events if e[0] <= now < e[1]), None)
    upcoming = next((e for e in events if e[0] > now), None)
    result = {"power": "есть" if current is None else ("возможно нет" if current[2] == "possible" else "нет")}
    if current:
        result["until"] = current[1].strftime("%d.%m %H:%M")
    if upcoming:
        result["next_outage"] = {
            "from": upcoming[0].strftime("%d.%m %H:%M"),
            "to": upcoming[1].strftime("%d.%m %H:%M"),
            "kind": "возможное" if upcoming[2] == "possible" else "точное",
        }
    return result
