from datetime import date

import httpx
import pytest
import respx

from outage_bot.core.http import SourceSchemaError
from outage_bot.core.providers.zoe import (
    SHEET_CSV,
    ZoeSheetsAddress,
    ZoeSiteSchedule,
    house_matches,
    parse_posts,
    parse_sheet,
)
from tests.conftest import load_text

PAGE = "zaporizhzhia/zoe/outage_page.html"
SHEETS = {"1.1": "s11", "6.1": "s61"}


def hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def intervals(slots):
    return [f"{hm(s.start)}-{hm(s.end)}" for s in slots]


def test_latest_update_wins():
    day = parse_posts(load_text(PAGE), date(2026, 10, 17))[date(2026, 10, 17)]
    assert intervals(day["1.1"]) == ["10:30-13:30", "17:00-18:30"]
    assert intervals(day["3.1"]) == ["16:30-19:30"]
    assert intervals(day["6.1"]) == ["14:00-17:30"]


def test_no_outages_post_and_business_post_ignored():
    posts = parse_posts(load_text(PAGE), date(2026, 10, 22))
    assert all(slots == [] for slots in posts[date(2026, 10, 6)].values())
    assert date(2026, 10, 18) not in posts


def test_year_inferred_near_today():
    assert date(2026, 9, 20) in parse_posts(load_text(PAGE), date(2026, 10, 22))
    assert date(2027, 9, 20) in parse_posts(load_text(PAGE), date(2027, 6, 1))


def test_group_missing_in_post_means_no_outages():
    page = '<article id="post-1"><h2>17 ЖОВТНЯ ДІЯТИМУТЬ ГПВ</h2><p>1.2: 09:30 – 13:30<br />2.2: 13:00 – 24:00</p></article>'
    day = parse_posts(page, date(2026, 10, 17))[date(2026, 10, 17)]
    assert day["1.1"] == [] and intervals(day["2.2"]) == ["13:00-24:00"]


def test_broken_page_raises():
    with pytest.raises(SourceSchemaError):
        parse_posts("<html></html>", date(2026, 10, 22))


@respx.mock
async def test_schedule_unknown_when_not_published(client):
    respx.get("https://www.zoe.com.ua/outage/").mock(return_value=httpx.Response(200, text=load_text(PAGE)))
    groups = await ZoeSiteSchedule(client, "zoe", "https://www.zoe.com.ua/outage/").get_all(date(2026, 10, 22))
    assert [d.status for d in groups["1.1"].days] == ["unknown", "unknown"]
    groups = await ZoeSiteSchedule(client, "zoe", "https://www.zoe.com.ua/outage/").get_all(date(2026, 10, 17))
    assert groups["1.1"].days[0].status == "schedule"


def test_parse_sheet_fixture():
    rows = parse_sheet(load_text("zaporizhzhia/zoe/addresses_gviz_1.1.csv"))
    assert ("бул. Шевченка", rows[0][1]) == rows[0] and "12" in rows[0][1].split("|")


@pytest.mark.parametrize(
    "token,house,ok",
    [
        ("12", "12", True),
        ("58/А", "58а", True),
        ("34-40", "36", True),
        ("34-40", "35", False),
        ("39-61", "41", True),
        ("39-61", "42", False),
        ("1-6", "4", True),
        ("108–136", "120", True),
        ("16 (п.1,2)  (9 пов)", "16", True),
        ("2-14", "2А", False),
    ],
)
def test_house_matches(token, house, ok):
    assert house_matches(token, house)[0] is ok


@respx.mock
async def test_sheets_lookup_old_name_and_multi_group(client):
    for group, sid in SHEETS.items():
        respx.get(SHEET_CSV.format(id=sid)).mock(
            return_value=httpx.Response(200, text=load_text(f"zaporizhzhia/zoe/addresses_gviz_{group}.csv"))
        )
    provider = ZoeSheetsAddress(client, SHEETS)
    assert [h.groups for h in (await provider.lookup("бул. Шевченка", "12")).hits] == [["1.1"]]
    assert [h.groups for h in (await provider.lookup("Автоклубна", "12")).hits] == [["1.1"]]
    assert [h.groups for h in (await provider.lookup("Виборзька", "12")).hits] == [["1.1"]]
    assert [h.groups for h in (await provider.lookup("вул. Автобусна", "5")).hits] == [["6.1"]]
    assert (await provider.lookup("вул. Автобуснаа", "5")).suggestions
