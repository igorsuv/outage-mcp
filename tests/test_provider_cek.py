import httpx
import pytest
import respx

from outage_bot.core.http import SourceSchemaError
from outage_bot.core.providers.cek_site import URL, CekSiteAddress, parse_locations, parse_queue
from tests.conftest import load_text

PAGE = "dnipro/cek/cek_site_viznachennya_chergy.html"


def test_parse_locations_fixture():
    data = parse_locations(load_text(PAGE))
    assert "м. Дніпро" in data and len(data["м. Дніпро"]) > 100
    assert data["м. Дніпро"]["просп. Олександра Поля"]["82"] == "Черга 5.2"


def test_parse_locations_broken_page():
    with pytest.raises(SourceSchemaError):
        parse_locations("<html>редизайн сайта</html>")


@pytest.mark.parametrize(
    "value,groups,has_note",
    [
        ("Черга 1.2", ["1.2"], False),
        ("Черга 2.1 та 6.1", ["2.1", "6.1"], True),
        ("Черга 2", ["2"], True),
        ("4.1", ["4.1"], False),
        ('Група 5.1 (АТ "ДТЕК ДЕМ")', ["5.1"], True),
    ],
)
def test_parse_queue(value, groups, has_note):
    got, note = parse_queue(value)
    assert got == groups and bool(note) == has_note


@pytest.mark.parametrize(
    "street,house,groups",
    [
        ("просп. Олександра Поля", "82", ["5.2"]),
        ("пр-т Поля Олександра", "84", ["5.2"]),
        ("вул. Робоча", "160", ["3.2"]),
        ("Моршинська", "6", ["1.1"]),
        ("Кисловодська", "6", ["1.1"]),
    ],
)
@respx.mock
async def test_lookup(client, street, house, groups):
    respx.get(URL).mock(return_value=httpx.Response(200, text=load_text(PAGE)))
    result = await CekSiteAddress(client, "м. Дніпро").lookup(street, house)
    assert [h.groups for h in result.hits] == [groups]


@respx.mock
async def test_lookup_unknown_street_suggests(client):
    respx.get(URL).mock(return_value=httpx.Response(200, text=load_text(PAGE)))
    result = await CekSiteAddress(client, "м. Дніпро").lookup("вул. Робочая", "160")
    assert result.hits == [] and "вул. Робоча" in result.suggestions
