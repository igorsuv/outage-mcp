import asyncio
import logging

from rapidfuzz import fuzz, process

from outage_bot.core.models import AddressMatch, LookupResult
from outage_bot.core.normalize import loose_key
from outage_bot.core.registry import Registry

log = logging.getLogger(__name__)


async def lookup(registry: Registry, city: str, street: str, house: str) -> LookupResult:
    """Ищет адрес; если не нашёлся — пробует актуальное название переименованной улицы."""
    result = await _lookup(registry, city, street, house)
    if result.status != "not_found":
        return result
    for new in renamed(registry.cities[city].renames, street):
        retry = await _lookup(registry, city, new, house)
        if retry.status != "not_found":
            for m in retry.matches:
                m.note = "; ".join(filter(None, [f"улица переименована: {street} → {new}", m.note]))
            return retry
    return result


def renamed(renames: dict[str, list[str]], street: str) -> list[str]:
    """Актуальные названия по старому, с допуском опечаток и русского написания."""
    keys = {}
    for old, new in renames.items():
        keys.setdefault(loose_key(old), []).extend(new)
    best = process.extractOne(loose_key(street), list(keys), scorer=fuzz.ratio, score_cutoff=80)
    return list(dict.fromkeys(keys[best[0]])) if best else []


async def _lookup(registry: Registry, city: str, street: str, house: str) -> LookupResult:
    """Ищет адрес у всех операторов города параллельно."""
    c = registry.cities[city]
    ops = list(c.address)
    results = await asyncio.gather(*(c.address[op].lookup(street, house) for op in ops), return_exceptions=True)

    matches, suggestions, unavailable = [], [], []
    for op, res in zip(ops, results):
        if isinstance(res, Exception):
            log.warning("address source failed", extra={"city": city, "operator": op, "error": repr(res)})
            unavailable.append(op)
            continue
        suggestions += [s for s in res.suggestions if s not in suggestions]
        seen = set()
        for hit in res.hits:
            groups = tuple(sorted(hit.groups))
            if groups in seen:
                continue
            seen.add(groups)
            matches.append(AddressMatch(city=city, operator=op, street=hit.street, house=hit.house, groups=list(groups), note=hit.note))

    if unavailable:
        status = "unavailable"
    elif not matches:
        status = "not_found"
    elif len(matches) == 1 and len(matches[0].groups) == 1:
        status = "found"
    else:
        status = "ambiguous"
    return LookupResult(status=status, matches=matches, suggestions=suggestions[:10], unavailable=unavailable)
