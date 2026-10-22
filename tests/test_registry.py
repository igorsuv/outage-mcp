import httpx
import pytest

from outage_bot.core.providers.cek_site import CekSiteAddress
from outage_bot.core.providers.yasno import YasnoAddress, YasnoSchedule
from outage_bot.core.providers.zoe import ZoeSheetsAddress, ZoeSiteSchedule
from outage_bot.core.registry import load_registry


async def test_default_config():
    async with httpx.AsyncClient() as client:
        r = load_registry(client)
    assert set(r.cities) == {"dnipro", "pokrov", "zaporizhzhia"}
    assert list(r.cities["dnipro"].address) == ["dtek_dnem", "cek"]
    assert isinstance(r.cities["dnipro"].address["cek"], CekSiteAddress)
    assert r.cities["pokrov"].address["dtek_dnem"].params["cityId"] == 20
    assert isinstance(r.cities["zaporizhzhia"].address["zoe"], ZoeSheetsAddress)
    assert isinstance(r.schedules["cek"], YasnoSchedule) and r.schedules["cek"].url.endswith("/dsos/303/planned-outages")
    assert isinstance(r.schedules["zoe"], ZoeSiteSchedule)


NEW_CITY = """
operators:
  dtek_dnem:
    name: ДТЕК Дніпровські електромережі
    schedule: {provider: yasno, region_id: 3, dso_id: 301}
cities:
  pavlohrad:
    name: Павлоград
    operators:
      - operator: dtek_dnem
        address: {provider: yasno, region_id: 3, dso_id: 301, city_id: 7}
"""


async def test_new_city_from_config_only(tmp_path):
    path = tmp_path / "cities.yaml"
    path.write_text(NEW_CITY, encoding="utf-8")
    async with httpx.AsyncClient() as client:
        r = load_registry(client, path)
    assert isinstance(r.cities["pavlohrad"].address["dtek_dnem"], YasnoAddress)


@pytest.mark.parametrize("bad", [NEW_CITY.replace("operator: dtek_dnem", "operator: ghost"), NEW_CITY.replace("provider: yasno, region_id: 3, dso_id: 301, city_id", "provider: nope, city_id")])
async def test_bad_config_fails_fast(tmp_path, bad):
    path = tmp_path / "cities.yaml"
    path.write_text(bad, encoding="utf-8")
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError):
            load_registry(client, path)
