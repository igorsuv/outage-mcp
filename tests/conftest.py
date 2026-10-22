import json
import pathlib

import httpx
import pytest
import respx

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load_json(rel: str):
    return json.loads((FIXTURES / rel).read_text(encoding="utf-8"))


def load_text(rel: str) -> str:
    return (FIXTURES / rel).read_text(encoding="utf-8")


def mock_yasno_lookup(router: respx.Router, rel: str, *, dso_id: int) -> None:
    """Мокает streets/houses/group YASNO по сохранённой фикстуре поиска адреса из этапа 0."""
    data = load_json(rel)
    base = "https://app.yasno.ua/api/blackout-service/public/shutdowns/addresses/v2"
    houses = data.get("houses", {})
    groups = {(r["street"]["id"], r["house"]["id"]): r["group"] for r in data["results"]}

    def streets(request: httpx.Request):
        assert request.url.params["dsoId"] == str(dso_id)
        return httpx.Response(200, json=data["streets"])

    def houses_handler(request: httpx.Request):
        items = houses.get(request.url.params["streetId"])
        return httpx.Response(200, json=items) if items is not None else httpx.Response(404, json={})

    def group(request: httpx.Request):
        key = (int(request.url.params["streetId"]), int(request.url.params["houseId"]))
        return httpx.Response(200, json=groups[key]) if key in groups else httpx.Response(404, json={})

    router.get(f"{base}/streets").mock(side_effect=streets)
    router.get(f"{base}/houses").mock(side_effect=houses_handler)
    router.get(f"{base}/group").mock(side_effect=group)


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c
