from datetime import date, datetime

import httpx
from pydantic import BaseModel, RootModel, ValidationError
from rapidfuzz import fuzz, process

from outage_bot.core.http import SourceSchemaError, TTLCache, request
from outage_bot.core.models import DaySchedule, GroupSchedule, Slot
from outage_bot.core.normalize import house_key, search_token, street_aliases, street_key
from outage_bot.core.providers.base import AddressHits, Hit

BASE = "https://app.yasno.ua/api/blackout-service/public/shutdowns"

_STATUS = {
    "ScheduleApplies": "schedule",
    "NoOutages": "no_outages",
    "WaitingForSchedule": "waiting",
    "EmergencyShutdowns": "emergency",
}
_SLOT_KIND = {"Definite": "definite", "Possible": "possible", "NotPlanned": None}


class _Slot(BaseModel):
    start: int
    end: int
    type: str


class _Day(BaseModel):
    slots: list[_Slot]
    date: datetime
    status: str


class _Group(BaseModel):
    today: _Day | None = None
    tomorrow: _Day | None = None
    updatedOn: datetime | None = None


class _PlannedOutages(RootModel[dict[str, _Group]]):
    pass


class _Item(BaseModel):
    id: int
    value: str


class _Items(RootModel[list[_Item]]):
    pass


class _GroupRef(BaseModel):
    group: int | str
    subgroup: int | str | None = 0


def _day(raw: _Day) -> DaySchedule:
    if raw.status not in _STATUS:
        raise SourceSchemaError(f"YASNO: неизвестный статус {raw.status!r}")
    slots = []
    for s in raw.slots:
        if s.type not in _SLOT_KIND:
            raise SourceSchemaError(f"YASNO: неизвестный тип слота {s.type!r}")
        if _SLOT_KIND[s.type]:
            slots.append(Slot(start=s.start, end=s.end, kind=_SLOT_KIND[s.type]))
    return DaySchedule(date=raw.date.date(), status=_STATUS[raw.status], slots=slots)


def parse_planned_outages(payload: object, operator: str) -> dict[str, GroupSchedule]:
    try:
        groups = _PlannedOutages.model_validate(payload).root
        return {
            name: GroupSchedule(
                operator=operator,
                group=name,
                days=[_day(d) for d in (g.today, g.tomorrow) if d],
                updated_at=g.updatedOn,
            )
            for name, g in groups.items()
        }
    except ValidationError as exc:
        raise SourceSchemaError(f"YASNO planned-outages: {exc}") from exc


class YasnoSchedule:
    def __init__(self, client: httpx.AsyncClient, operator: str, region_id: int, dso_id: int):
        self.client, self.operator = client, operator
        self.url = f"{BASE}/regions/{region_id}/dsos/{dso_id}/planned-outages"
        self._cache = TTLCache(ttl=300)

    async def _load(self) -> dict[str, GroupSchedule]:
        resp = await request(self.client, "GET", self.url)
        return parse_planned_outages(resp.json(), self.operator)

    async def get_all(self, today: date) -> dict[str, GroupSchedule]:
        return await self._cache.get(self._load)


class YasnoAddress:
    def __init__(self, client: httpx.AsyncClient, region_id: int, dso_id: int, city_id: int):
        self.client = client
        self.params = {"regionId": region_id, "dsoId": dso_id, "cityId": city_id}

    async def _get(self, path: str, model, **params):
        resp = await request(self.client, "GET", f"{BASE}/addresses/v2/{path}", params={**self.params, **params}, ok_statuses=(404,))
        if resp.status_code == 404:
            return None
        try:
            return model.model_validate(resp.json())
        except ValidationError as exc:
            raise SourceSchemaError(f"YASNO {path}: {exc}") from exc

    async def lookup(self, street: str, house: str) -> AddressHits:
        key = street_key(street)
        found = await self._get("streets", _Items, query=search_token(street))
        streets = found.root if found else []
        exact = [s for s in streets if key in street_aliases(s.value)]
        if not exact:
            choices = {s.value: street_key(s.value) for s in streets}
            best = process.extract(key, choices, scorer=fuzz.token_set_ratio, limit=5, score_cutoff=70)
            return AddressHits(suggestions=[name for _, _, name in best])

        hits = []
        for s in exact:
            houses = await self._get("houses", _Items, streetId=s.id, query=house)
            for h in (houses.root if houses else []):
                if house_key(h.value) != house_key(house):
                    continue
                ref = await self._get("group", _GroupRef, streetId=s.id, houseId=h.id)
                if ref:
                    group = f"{ref.group}.{ref.subgroup}" if ref.subgroup not in (0, "0", None) else str(ref.group)
                    hits.append(Hit(street=s.value, house=h.value, groups=[group]))
        if not hits:
            return AddressHits(suggestions=[f"{s.value}: дом {house} не найден" for s in exact])
        return AddressHits(hits=hits)
