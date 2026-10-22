from datetime import date, datetime, timezone

import pytest

from outage_bot.core.models import KYIV, DaySchedule, GroupSchedule, Slot
from outage_bot.core.power import day_summary, merged_intervals, power_now


def sched(*days):
    return GroupSchedule(operator="x", group="1.1", days=list(days))


def day(d, slots=(), status="schedule"):
    return DaySchedule(date=d, status=status, slots=[Slot(start=a, end=b, kind=k) for a, b, k in slots])


D = date(2026, 11, 3)
TOMORROW = date(2026, 11, 4)


def at(h, m=0, d=D):
    return datetime(d.year, d.month, d.day, h, m, tzinfo=KYIV)


def test_merge_adjacent_slots_same_kind_only():
    d = day(D, [(480, 510, "definite"), (510, 690, "definite"), (690, 720, "possible")])
    assert merged_intervals(d) == [(480, 690, "definite"), (690, 720, "possible")]
    assert day_summary(d)["no_power"] == ["08:00–11:30", "11:30–12:00 (возможно)"]


@pytest.mark.parametrize(
    "now,power",
    [(at(7, 59), "есть"), (at(8), "нет"), (at(11, 29), "нет"), (at(11, 30), "есть"), (at(13), "возможно нет")],
)
def test_power_now_boundaries(now, power):
    s = sched(day(D, [(480, 690, "definite"), (780, 840, "possible")]))
    assert power_now(s, now)["power"] == power


def test_until_and_next_outage():
    s = sched(day(D, [(480, 690, "definite"), (1080, 1200, "definite")]))
    r = power_now(s, at(9))
    assert r["until"] == "03.11 11:30" and r["next_outage"]["from"] == "03.11 18:00"


def test_outage_across_midnight_is_one_interval():
    s = sched(day(D, [(1320, 1440, "definite")]), day(TOMORROW, [(0, 120, "definite")]))
    assert power_now(s, at(23))["until"] == "04.11 02:00"


def test_next_outage_tomorrow_when_today_clear():
    s = sched(day(D, status="no_outages"), day(TOMORROW, [(600, 720, "definite")]))
    r = power_now(s, at(20))
    assert r["power"] == "есть" and r["next_outage"]["from"] == "04.11 10:00"


@pytest.mark.parametrize("status,power", [("unknown", "неизвестно"), ("waiting", "неизвестно"), ("emergency", "возможно нет")])
def test_special_statuses(status, power):
    assert power_now(sched(day(D, status=status)), at(12))["power"] == power


def test_empty_schedule_means_power():
    assert power_now(sched(day(D, status="no_outages")), at(12)) == {"power": "есть"}


def test_now_in_utc_is_converted_to_kyiv():
    s = sched(day(D, [(480, 690, "definite")]))
    assert power_now(s, datetime(2026, 11, 3, 6, 30, tzinfo=timezone.utc))["power"] == "нет"


def test_dst_end_day_wall_clock():
    """25.10.2026 переход на зимнее время: 03:00 EEST -> 02:00 EET, слоты — по местным часам."""
    dst = date(2026, 10, 25)
    s = sched(day(dst, [(240, 360, "definite")]))
    assert power_now(s, datetime(2026, 10, 25, 2, 30, tzinfo=timezone.utc))["power"] == "нет"
    assert power_now(s, datetime(2026, 10, 25, 4, 0, tzinfo=timezone.utc))["power"] == "есть"


def test_dst_start_day_wall_clock():
    """29.03.2026 переход на летнее время: 03:00 EET -> 04:00 EEST."""
    dst = date(2026, 3, 29)
    s = sched(day(dst, [(300, 420, "definite")]))
    assert power_now(s, datetime(2026, 3, 29, 2, 30, tzinfo=timezone.utc))["power"] == "нет"
    assert power_now(s, datetime(2026, 3, 29, 1, 30, tzinfo=timezone.utc))["power"] == "есть"
