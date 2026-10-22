from datetime import date
from typing import Protocol

from pydantic import BaseModel

from outage_bot.core.models import GroupSchedule

ALL_GROUPS = [f"{q}.{s}" for q in range(1, 7) for s in (1, 2)]


class Hit(BaseModel):
    street: str
    house: str
    groups: list[str]
    note: str | None = None


class AddressHits(BaseModel):
    hits: list[Hit] = []
    suggestions: list[str] = []


class AddressProvider(Protocol):
    async def lookup(self, street: str, house: str) -> AddressHits: ...


class ScheduleProvider(Protocol):
    async def get_all(self, today: date) -> dict[str, GroupSchedule]: ...
