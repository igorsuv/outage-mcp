from datetime import datetime

import httpx
import pytest
import respx
from mcp.client.client import Client

from outage_bot.core.models import KYIV
from outage_bot.core.providers.cek_site import URL as CEK_URL
from outage_bot.core.registry import load_registry
from outage_bot.mcp_server import server as srv
from tests.conftest import load_json, load_text, mock_yasno_lookup

PLANNED = "https://app.yasno.ua/api/blackout-service/public/shutdowns/regions/3/dsos/{}/planned-outages"


@pytest.fixture
def frozen_now(monkeypatch):
    monkeypatch.setattr(srv, "_now", lambda: datetime(2026, 10, 22, 17, 0, tzinfo=KYIV))


async def call(tool, args):
    async with httpx.AsyncClient() as http:
        async with Client(srv.build_server(load_registry(http))) as c:
            return (await c.call_tool(tool, args)).structured_content


async def test_tools_listed():
    async with httpx.AsyncClient() as http:
        async with Client(srv.build_server(load_registry(http))) as c:
            names = {t.name for t in (await c.list_tools()).tools}
    assert names == {"check_address", "get_group_schedule"}


@respx.mock(assert_all_called=False)
async def test_check_address_found_with_schedule(respx_mock, frozen_now):
    mock_yasno_lookup(respx_mock, "dnipro/dtek_dnem/yasno_lookup/олександра_поля_18.json", dso_id=301)
    respx_mock.get(CEK_URL).mock(return_value=httpx.Response(200, text=load_text("dnipro/cek/cek_site_viznachennya_chergy.html")))
    respx_mock.get(PLANNED.format(301)).mock(return_value=httpx.Response(200, json=load_json("dnipro/dtek_dnem/yasno_planned_outages.json")))
    r = await call("check_address", {"city": "dnipro", "street": "Олександра Поля", "house": "18"})
    assert r["status"] == "found"
    (addr,) = r["addresses"]
    assert addr["groups"] == ["3.1"] and addr["schedule"]["groups"]["3.1"]["power_now"] == {"power": "есть"}


@respx.mock(assert_all_called=False)
async def test_schedule_source_broken_does_not_break_lookup(respx_mock, frozen_now):
    mock_yasno_lookup(respx_mock, "pokrov/dtek_dnem/yasno_lookup/осипенка_2.json", dso_id=301)
    respx_mock.get(PLANNED.format(301)).mock(return_value=httpx.Response(200, json={"1.1": {"today": "garbage"}}))
    r = await call("check_address", {"city": "pokrov", "street": "Осипенка", "house": "2"})
    assert r["status"] == "found" and "error" in r["addresses"][0]["schedule"]


async def test_unknown_city():
    r = await call("check_address", {"city": "kharkiv", "street": "x", "house": "1"})
    assert "error" in r


@respx.mock
async def test_group_without_subgroup_expands(respx_mock, frozen_now):
    respx_mock.get(PLANNED.format(303)).mock(return_value=httpx.Response(200, json=load_json("dnipro/cek/yasno_planned_outages.json")))
    r = await call("get_group_schedule", {"operator": "cek", "group": "2"})
    assert set(r["groups"]) == {"2.1", "2.2"}


async def test_healthz_route():
    async with httpx.AsyncClient() as http:
        app = srv.build_server(load_registry(http)).streamable_http_app(streamable_http_path="/mcp/s")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            assert (await c.get("/healthz")).text == "ok"
