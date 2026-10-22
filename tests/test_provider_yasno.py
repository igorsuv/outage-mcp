from datetime import date

import httpx
import pytest
import respx

from outage_bot.core.http import SourceSchemaError
from outage_bot.core.providers.yasno import YasnoAddress, YasnoSchedule, parse_planned_outages
from tests.conftest import load_json, mock_yasno_lookup

PLANNED = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/3/dsos/301/planned-outages"


def test_parse_dnipro_no_outages_fixture():
    groups = parse_planned_outages(load_json("dnipro/dtek_dnem/yasno_planned_outages.json"), "dtek_dnem")
    assert set(groups) >= {"1.1", "3.1", "6.2"}
    today, tomorrow = groups["3.1"].days
    assert (today.date, today.status, today.slots) == (date(2026, 10, 22), "no_outages", [])
    assert tomorrow.status == "waiting"


def test_parse_slots_definite_and_not_planned_skipped():
    groups = parse_planned_outages(load_json("_schema_samples/yasno_kyiv_region25_dso902_planned_outages.json"), "x")
    slots = groups["1.1"].days[0].slots
    assert slots[0].model_dump() == {"start": 0, "end": 30, "kind": "definite"}
    assert all(s.kind in ("definite", "possible") for s in slots)
    assert (750, 1020) in [(s.start, s.end) for s in slots]
    assert (30, 750) not in [(s.start, s.end) for s in slots]


def _payload(status="ScheduleApplies", slot_type="Definite", end=1440):
    day = {"slots": [{"start": 1320, "end": end, "type": slot_type}], "date": "2026-10-25T00:00:00+02:00", "status": status}
    return {"1.1": {"today": day, "updatedOn": "2026-10-25T00:00:00+00:00"}}


def test_slot_until_midnight_and_possible():
    slot = parse_planned_outages(_payload(slot_type="Possible"), "x")["1.1"].days[0].slots[0]
    assert (slot.start, slot.end, slot.kind) == (1320, 1440, "possible")


def test_emergency_status():
    assert parse_planned_outages(_payload(status="EmergencyShutdowns"), "x")["1.1"].days[0].status == "emergency"


@pytest.mark.parametrize(
    "payload",
    [_payload(status="SomethingNew"), _payload(slot_type="Maybe"), _payload(end=1500), {"1.1": {"today": {"slots": "x"}}}, []],
)
def test_broken_schema_raises(payload):
    with pytest.raises(SourceSchemaError):
        parse_planned_outages(payload, "x")


@respx.mock
async def test_schedule_one_request_for_many_calls(client):
    route = respx.get(PLANNED).mock(return_value=httpx.Response(200, json=load_json("dnipro/dtek_dnem/yasno_planned_outages.json")))
    provider = YasnoSchedule(client, "dtek_dnem", 3, 301)
    for _ in range(5):
        await provider.get_all(date(2026, 10, 22))
    assert route.call_count == 1


@pytest.mark.parametrize(
    "fixture,dso,street,house,expected",
    [
        ("dnipro/dtek_dnem/yasno_lookup/олександра_поля_18.json", 301, "просп. Олександра Поля", "18", {"3.1"}),
        ("dnipro/dtek_dnem/yasno_lookup/слобожанський_31.json", 301, "Слобожанський", "31", {"3.2"}),
        ("dnipro/dtek_dnem/yasno_lookup/дмитра_яворницького_50.json", 301, "проспект Дмитра Яворницького", "50", {"5.2"}),
        ("dnipro/cek/yasno_lookup/робоча_160.json", 303, "вул. Робоча", "160", {"1.2"}),
        ("pokrov/dtek_dnem/yasno_lookup/осипенка_2.json", 301, "вулиця Осипенка", "2", {"1.1"}),
    ],
)
async def test_address_found(client, fixture, dso, street, house, expected):
    with respx.mock(assert_all_called=False) as router:
        mock_yasno_lookup(router, fixture, dso_id=dso)
        result = await YasnoAddress(client, 3, dso, 6).lookup(street, house)
    assert {g for h in result.hits for g in h.groups} == expected


async def test_address_not_found_gives_suggestions(client):
    with respx.mock(assert_all_called=False) as router:
        mock_yasno_lookup(router, "dnipro/dtek_dnem/yasno_lookup/гагаріна_72.json", dso_id=301)
        result = await YasnoAddress(client, 3, 301, 6).lookup("просп. Гагаріна", "72")
    assert result.hits == [] and result.suggestions
