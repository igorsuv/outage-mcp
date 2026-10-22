import pathlib
from dataclasses import dataclass, field

import httpx
import yaml

from outage_bot.core.providers.base import AddressProvider, ScheduleProvider
from outage_bot.core.providers.cek_site import CekSiteAddress
from outage_bot.core.providers.yasno import YasnoAddress, YasnoSchedule
from outage_bot.core.providers.zoe import ZoeSheetsAddress, ZoeSiteSchedule

DEFAULT_CONFIG = pathlib.Path(__file__).parent.parent / "config" / "cities.yaml"

ADDRESS_PROVIDERS = {"yasno": YasnoAddress, "cek_site": CekSiteAddress, "zoe_sheets": ZoeSheetsAddress}
SCHEDULE_PROVIDERS = {"yasno": YasnoSchedule, "zoe_site": ZoeSiteSchedule}


@dataclass
class City:
    key: str
    name: str
    address: dict[str, AddressProvider] = field(default_factory=dict)


@dataclass
class Registry:
    cities: dict[str, City]
    operator_names: dict[str, str]
    schedules: dict[str, ScheduleProvider]


def _build(table: dict, client: httpx.AsyncClient, conf: dict, **extra):
    conf = dict(conf)
    kind = conf.pop("provider")
    if kind not in table:
        raise ValueError(f"Неизвестный provider {kind!r}")
    return table[kind](client, **extra, **conf)


def load_registry(client: httpx.AsyncClient, path: pathlib.Path = DEFAULT_CONFIG) -> Registry:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    operators = raw["operators"]
    schedules = {op: _build(SCHEDULE_PROVIDERS, client, conf["schedule"], operator=op) for op, conf in operators.items()}
    cities = {}
    for key, conf in raw["cities"].items():
        city = City(key=key, name=conf["name"])
        for entry in conf["operators"]:
            if entry["operator"] not in operators:
                raise ValueError(f"Город {key}: неизвестный оператор {entry['operator']!r}")
            city.address[entry["operator"]] = _build(ADDRESS_PROVIDERS, client, entry["address"])
        cities[key] = city
    return Registry(cities=cities, operator_names={op: c["name"] for op, c in operators.items()}, schedules=schedules)
