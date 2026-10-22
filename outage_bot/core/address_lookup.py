import asyncio
import logging

from outage_bot.core.models import AddressMatch, LookupResult
from outage_bot.core.registry import Registry

log = logging.getLogger(__name__)


async def lookup(registry: Registry, city: str, street: str, house: str) -> LookupResult:
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
