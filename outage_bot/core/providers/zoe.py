import asyncio
import csv
import html as htmllib
import io
import re
from datetime import date, timedelta

import httpx
from rapidfuzz import fuzz, process

from outage_bot.core.http import SourceSchemaError, TTLCache, request
from outage_bot.core.models import DaySchedule, GroupSchedule, Slot
from outage_bot.core.normalize import house_key, street_aliases, street_key
from outage_bot.core.providers.base import ALL_GROUPS, AddressHits, Hit

SHEET_CSV = "https://docs.google.com/spreadsheets/d/{id}/gviz/tq?tqx=out:csv"
MONTHS = {
    "січня": 1, "лютого": 2, "березня": 3, "квітня": 4, "травня": 5, "червня": 6,
    "липня": 7, "серпня": 8, "вересня": 9, "жовтня": 10, "листопада": 11, "грудня": 12,
}
_DATE_RE = re.compile(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")", re.I)
_LINE_RE = re.compile(r"^\s*(\d\.\d)\s*:\s*(.+)$", re.M)
_INTERVAL_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[–—-]\s*(\d{1,2}):(\d{2})")
_NO_OUTAGES_RE = re.compile(r"НЕ\s+ЗАПЛАНОВАН|НЕ\s+ЗАСТОСОВУВАТИМ|НЕ\s+ПРОГНОЗУ|НЕ\s+ДІЯТИМУТЬ", re.I)
_NOT_POPULATION_RE = re.compile(r"ПРОМИСЛОВОСТІ|БІЗНЕС", re.I)


# ---------- адреса: Google Sheets, одна таблица на подчергу ----------

def parse_sheet(text: str) -> list[tuple[str, str]]:
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2 or [c.strip() for c in rows[1][:2]] != ["Вулиця", "Будинок"]:
        raise SourceSchemaError("ЗОЕ: таблица адресов без заголовка 'Вулиця,Будинок'")
    return [(r[0].strip(), r[1]) for r in rows[2:] if len(r) >= 2 and r[0].strip()]


def house_matches(token: str, house: str) -> tuple[bool, str | None]:
    """Токен из таблицы: '12', '58/А', '34-40' (диапазон), '16 (п.1,2) (9 пов)' (часть дома)."""
    raw = token.strip()
    base = raw.split("(")[0].strip()
    note = f"в таблице ЗОЕ: «{raw}»" if "(" in raw else None
    rng = re.fullmatch(r"(\d+)\s*[-–]\s*(\d+)", base)
    if rng:
        n = re.fullmatch(r"\d+", house_key(house))
        if not n:
            return False, None
        a, b, x = int(rng[1]), int(rng[2]), int(n[0])
        same_parity = a % 2 == b % 2
        ok = min(a, b) <= x <= max(a, b) and (not same_parity or x % 2 == a % 2)
        return ok, f"входит в диапазон «{raw}» из таблицы ЗОЕ (интерпретация диапазона)"
    return house_key(base) == house_key(house), note


class ZoeSheetsAddress:
    def __init__(self, client: httpx.AsyncClient, sheets: dict[str, str]):
        self.client, self.sheets = client, sheets
        self._cache = TTLCache(ttl=24 * 3600)

    async def _load(self) -> dict[str, list[tuple[str, str, str]]]:
        async def one(group: str, sid: str):
            resp = await request(self.client, "GET", SHEET_CSV.format(id=sid))
            return group, parse_sheet(resp.text)

        index: dict[str, list[tuple[str, str, str]]] = {}
        for group, rows in await asyncio.gather(*(one(g, s) for g, s in self.sheets.items())):
            for street, houses in rows:
                for key in street_aliases(street):
                    index.setdefault(key, []).extend((street, h, group) for h in houses.split("|") if h.strip())
        return index

    async def lookup(self, street: str, house: str) -> AddressHits:
        index = await self._cache.get(self._load)
        key = street_key(street)
        if key not in index:
            best = process.extract(key, list(index), scorer=fuzz.token_set_ratio, limit=5, score_cutoff=80)
            names = {index[k][0][0] for k, _, _ in best}
            return AddressHits(suggestions=sorted(names))
        by_street: dict[str, Hit] = {}
        for name, token, group in index[key]:
            ok, note = house_matches(token, house)
            if not ok:
                continue
            hit = by_street.setdefault(name, Hit(street=name, house=house, groups=[]))
            if group not in hit.groups:
                hit.groups.append(group)
            if note:
                hit.note = "; ".join(filter(None, [hit.note, f"{group}: {note}"]))
        return AddressHits(hits=list(by_street.values()))


# ---------- графики: текстовые посты на zoe.com.ua/outage/ ----------

def _infer_date(day: int, month: int, today: date) -> date:
    candidates = []
    for y in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            pass
    return min(candidates, key=lambda d: abs((d - today).days))


def _minutes(h: str, m: str) -> int:
    value = int(h) * 60 + int(m)
    if not 0 <= value <= 1440:
        raise SourceSchemaError(f"ЗОЕ: время вне суток {h}:{m}")
    return value


def parse_posts(page: str, today: date) -> dict[date, dict[str, list[Slot]]]:
    """Дата -> группа -> слоты. Для каждой даты берётся самый свежий пост. Группы без строк = без отключений."""
    posts = re.findall(r'<article id="post-(\d+)">\s*<h2>(.*?)</h2>(.*?)</article>', page, re.S)
    if not posts:
        raise SourceSchemaError("ЗОЕ: на странице нет постов <article>")
    result: dict[date, dict[str, list[Slot]]] = {}
    for _, title, body in sorted(posts, key=lambda p: int(p[0]), reverse=True):
        title = htmllib.unescape(re.sub(r"<[^>]+>", "", title))
        text = htmllib.unescape(re.sub(r"<br\s*/?>|</p>", "\n", body))
        text = re.sub(r"<[^>]+>", "", text)
        if _NOT_POPULATION_RE.search(title):
            continue
        m = _DATE_RE.search(title) or _DATE_RE.search(text)
        if not m:
            continue
        d = _infer_date(int(m[1]), MONTHS[m[2].lower()], today)
        if d in result:
            continue
        lines = _LINE_RE.findall(text)
        if lines:
            day = {g: [] for g in ALL_GROUPS}
            for group, intervals in lines:
                for h1, m1, h2, m2 in _INTERVAL_RE.findall(intervals):
                    start, end = _minutes(h1, m1), _minutes(h2, m2)
                    if end <= start:
                        end = 1440
                    day.setdefault(group, []).append(Slot(start=start, end=end))
            result[d] = day
        elif _NO_OUTAGES_RE.search(title + " " + text):
            result[d] = {g: [] for g in ALL_GROUPS}
    return result


class ZoeSiteSchedule:
    def __init__(self, client: httpx.AsyncClient, operator: str, url: str):
        self.client, self.operator, self.url = client, operator, url
        self._cache = TTLCache(ttl=300)

    async def _load(self) -> str:
        return (await request(self.client, "GET", self.url)).text

    async def get_all(self, today: date) -> dict[str, GroupSchedule]:
        posts = parse_posts(await self._cache.get(self._load), today)
        out = {}
        for group in ALL_GROUPS:
            days = []
            for d in (today, today + timedelta(days=1)):
                if d not in posts:
                    days.append(DaySchedule(date=d, status="unknown"))
                else:
                    slots = posts[d].get(group, [])
                    days.append(DaySchedule(date=d, status="schedule" if slots else "no_outages", slots=slots))
            out[group] = GroupSchedule(operator=self.operator, group=group, days=days)
        return out
