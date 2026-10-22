import httpx
import respx

from outage_bot.core.address_lookup import lookup
from outage_bot.core.http import SourceUnavailable
from outage_bot.core.providers.base import AddressHits, Hit
from outage_bot.core.providers.cek_site import URL as CEK_URL
from outage_bot.core.registry import City, Registry, load_registry
from tests.conftest import load_text, mock_yasno_lookup


class Stub:
    def __init__(self, result):
        self.result = result

    async def lookup(self, street, house):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def reg(**providers):
    return Registry(cities={"c": City(key="c", name="C", address=providers)}, operator_names={}, schedules={})


def hit(*groups, street="вул. Робоча"):
    return Hit(street=street, house="1", groups=list(groups))


async def test_found_at_one_operator():
    r = await lookup(reg(a=Stub(AddressHits(hits=[hit("3.1")])), b=Stub(AddressHits())), "c", "Робоча", "1")
    assert r.status == "found" and [(m.operator, m.groups) for m in r.matches] == [("a", ["3.1"])]


async def test_found_at_two_operators_is_ambiguous():
    r = await lookup(reg(a=Stub(AddressHits(hits=[hit("3.1")])), b=Stub(AddressHits(hits=[hit("5.2")]))), "c", "x", "1")
    assert r.status == "ambiguous" and {m.operator for m in r.matches} == {"a", "b"}


async def test_duplicate_street_spellings_same_group_collapse():
    hits = [hit("3.1", street="просп. Олександра Поля"), hit("3.1", street="просп. Поля Олександра")]
    r = await lookup(reg(a=Stub(AddressHits(hits=hits))), "c", "x", "1")
    assert r.status == "found" and len(r.matches) == 1


async def test_house_in_two_groups_is_ambiguous():
    r = await lookup(reg(a=Stub(AddressHits(hits=[hit("5.1", "5.2")]))), "c", "x", "1")
    assert r.status == "ambiguous"


async def test_not_found_merges_suggestions():
    r = await lookup(reg(a=Stub(AddressHits(suggestions=["вул. Робоча"])), b=Stub(AddressHits(suggestions=["вул. Робоча", "вул. Роботи"]))), "c", "x", "1")
    assert r.status == "not_found" and r.suggestions == ["вул. Робоча", "вул. Роботи"]


async def test_one_source_down_is_unavailable_not_wrong_operator():
    r = await lookup(reg(a=Stub(AddressHits(hits=[hit("3.1")])), b=Stub(SourceUnavailable("timeout"))), "c", "x", "1")
    assert r.status == "unavailable" and r.unavailable == ["b"]


async def test_dnipro_real_conflict_dnem_and_cek():
    """просп. Олександра Поля 82: ДнЕМ (YASNO) даёт 3.1, ЦЕК (cek.dp.ua) даёт 5.2 — показываем оба."""
    async with httpx.AsyncClient() as client:
        registry = load_registry(client)
        with respx.mock(assert_all_called=False) as router:
            mock_yasno_lookup(router, "dnipro/dtek_dnem/yasno_lookup/олександра_поля_82.json", dso_id=301)
            router.get(CEK_URL).mock(return_value=httpx.Response(200, text=load_text("dnipro/cek/cek_site_viznachennya_chergy.html")))
            r = await lookup(registry, "dnipro", "просп. Олександра Поля", "82")
    assert r.status == "ambiguous"
    assert sorted((m.operator, m.groups[0]) for m in r.matches) == [("cek", "5.2"), ("dtek_dnem", "3.1")]


async def test_dnipro_cek_source_down():
    async with httpx.AsyncClient() as client:
        registry = load_registry(client)
        with respx.mock(assert_all_called=False) as router:
            mock_yasno_lookup(router, "dnipro/dtek_dnem/yasno_lookup/олександра_поля_18.json", dso_id=301)
            router.get(CEK_URL).mock(return_value=httpx.Response(503))
            r = await lookup(registry, "dnipro", "просп. Олександра Поля", "18")
    assert r.status == "unavailable" and r.unavailable == ["cek"]


class ByStreet:
    def __init__(self, street, result):
        self.street, self.result = street, result

    async def lookup(self, street, house):
        return self.result if street == self.street else AddressHits(suggestions=[f"{street}: дом {house} не найден"])


def reg_renames(provider, renames):
    return Registry(cities={"c": City(key="c", name="C", address={"a": provider}, renames=renames)}, operator_names={}, schedules={})


async def test_old_street_name_resolves_to_new():
    r = await lookup(reg_renames(ByStreet("Вадима Жукова", AddressHits(hits=[hit("1.2", street="вул. Жукова Вадима")])), {"Бєляєва": ["Вадима Жукова"]}), "c", "вул. Бєляєва", "18")
    assert r.status == "found" and r.matches[0].groups == ["1.2"]
    assert "Бєляєва" in r.matches[0].note and "Вадима Жукова" in r.matches[0].note


async def test_old_street_name_with_typo_or_russian_spelling():
    p = ByStreet("Вадима Жукова", AddressHits(hits=[hit("1.2")]))
    for street in ("Беляєва", "Беляева", "Біляєва"):
        r = await lookup(reg_renames(p, {"Замполіта Бєляєва": ["Вадима Жукова"], "Бєляєва": ["Вадима Жукова"]}), "c", street, "18")
        assert r.status == "found", street


async def test_unrelated_street_not_renamed():
    r = await lookup(reg_renames(ByStreet("Вадима Жукова", AddressHits(hits=[hit("1.2")])), {"Бєляєва": ["Вадима Жукова"]}), "c", "Робоча", "18")
    assert r.status == "not_found"


def test_dnipro_renames_loaded():
    registry = load_registry(httpx.AsyncClient())
    assert registry.cities["dnipro"].renames["Замполіта Бєляєва"] == ["Вадима Жукова"]


def test_pokrov_renames_loaded():
    registry = load_registry(httpx.AsyncClient())
    assert registry.cities["pokrov"].renames["Газети Правди"] == ["Соборна"]
