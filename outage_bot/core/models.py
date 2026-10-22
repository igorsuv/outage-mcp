from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

KYIV = ZoneInfo("Europe/Kyiv")

DayStatus = Literal["schedule", "no_outages", "waiting", "emergency", "unknown"]


class Slot(BaseModel):
    start: int = Field(ge=0, le=1440)
    end: int = Field(ge=0, le=1440)
    kind: Literal["definite", "possible"] = "definite"


class DaySchedule(BaseModel):
    date: date
    status: DayStatus
    slots: list[Slot] = []


class GroupSchedule(BaseModel):
    operator: str
    group: str
    days: list[DaySchedule]
    updated_at: datetime | None = None


class AddressMatch(BaseModel):
    city: str
    operator: str
    street: str
    house: str
    groups: list[str]
    note: str | None = None


class LookupResult(BaseModel):
    status: Literal["found", "ambiguous", "not_found", "unavailable"]
    matches: list[AddressMatch] = []
    suggestions: list[str] = []
    unavailable: list[str] = []
