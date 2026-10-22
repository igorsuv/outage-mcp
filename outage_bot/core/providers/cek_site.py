import json
import re

import httpx
from rapidfuzz import fuzz, process

from outage_bot.core.http import SourceSchemaError, TTLCache, request
from outage_bot.core.normalize import house_key, street_aliases, street_key
from outage_bot.core.providers.base import AddressHits, Hit

URL = "https://cek.dp.ua/index.php/cpojivaham/pobutovi-spozhyvachi/viznachennya-chergy.html"
ALL_HOUSES = "Усі будинки"


def parse_locations(html: str) -> dict[str, dict[str, dict[str, str]]]:
    m = re.search(r"const\s+locations\s*=\s*", html)
    if not m:
        raise SourceSchemaError("ЦЕК: на странице нет `const locations`")
    try:
        data, _ = json.JSONDecoder().raw_decode(html[m.end():])
    except json.JSONDecodeError as exc:
        raise SourceSchemaError(f"ЦЕК: locations не JSON: {exc}") from exc
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise SourceSchemaError("ЦЕК: неожиданная структура locations")
    return data


def parse_queue(value: str) -> tuple[list[str], str | None]:
    """'Черга 1.2' -> ['1.2']; 'Черга 2.1 та 6.1' -> ['2.1','6.1']; 'Черга 2' -> ['2'] + пояснение."""
    groups = re.findall(r"\d\.\d|(?<![\d.])\d(?![\d.])", value)
    note = None
    if "ДТЕК" in value:
        note = f"ЦЕК указывает другого оператора: {value}"
    elif any("." not in g for g in groups):
        note = f"ЦЕК не указал подчергу: {value}"
    elif len(groups) > 1:
        note = f"ЦЕК указал несколько черг: {value}"
    return groups, note


class CekSiteAddress:
    def __init__(self, client: httpx.AsyncClient, city: str):
        self.client, self.city = client, city
        self._cache = TTLCache(ttl=24 * 3600)

    async def _load(self):
        resp = await request(self.client, "GET", URL)
        streets = parse_locations(resp.text).get(self.city)
        if streets is None:
            raise SourceSchemaError(f"ЦЕК: нет города {self.city!r}")
        return streets

    async def lookup(self, street: str, house: str) -> AddressHits:
        streets = await self._cache.get(self._load)
        key = street_key(street)
        exact = [name for name in streets if key in street_aliases(name)]
        if not exact:
            choices = {name: street_key(name) for name in streets}
            best = process.extract(key, choices, scorer=fuzz.token_set_ratio, limit=5, score_cutoff=80)
            return AddressHits(suggestions=[name for _, _, name in best])
        hits = []
        for name in exact:
            houses = streets[name]
            for h, value in houses.items():
                if h == ALL_HOUSES or house_key(h) == house_key(house):
                    groups, note = parse_queue(value)
                    hits.append(Hit(street=name, house=house if h == ALL_HOUSES else h, groups=groups, note=note))
        return AddressHits(hits=hits)
