"""MCP-сервер графиков отключений. Запуск: python -m outage_bot.mcp_server (см. README)."""

import logging
import os
from datetime import datetime
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from outage_bot.core.address_lookup import lookup
from outage_bot.core.http import SourceSchemaError, SourceUnavailable, make_client
from outage_bot.core.models import KYIV, GroupSchedule
from outage_bot.core.power import day_summary, power_now
from outage_bot.core.registry import Registry, load_registry

log = logging.getLogger(__name__)

INSTRUCTIONS = """Графики плановых отключений света для Днепра, Покрова и Запорожья (Украина).
Оператор и очередь определяются автоматически по адресу через check_address.
- Улицу передавай по-украински, без «вул./просп.»; дом — отдельно (например street="Олександра Поля", house="18").
- status=ambiguous: адрес найден у нескольких операторов или в нескольких очередях — покажи пользователю варианты
  и попроси уточнить (например, какой оператор указан в платёжке за распределение). Не выбирай сам.
- status=not_found: предложи варианты из suggestions. status=unavailable: источник не ответил, попроси повторить позже.
- Если нужна только очередь, которая уже известна, используй get_group_schedule.
Время — Europe/Kyiv. Отметка «возможно» означает возможное, а не точное отключение."""

LOOKUP_TEXT = {
    "found": "адрес найден",
    "ambiguous": "найдено несколько вариантов — нужно уточнение у пользователя",
    "not_found": "адрес не найден",
    "unavailable": "часть источников недоступна, повторите позже",
}


def _now() -> datetime:
    return datetime.now(KYIV)


async def _schedules(registry: Registry, operator: str, groups: list[str]) -> dict[str, Any]:
    now = _now()
    try:
        all_groups = await registry.schedules[operator].get_all(now.date())
    except (SourceUnavailable, SourceSchemaError) as exc:
        log.warning("schedule source failed", extra={"operator": operator, "error": repr(exc)})
        return {"error": f"не удалось получить график оператора: {exc.__class__.__name__}"}
    out = {}
    for g in groups:
        names = [g] if g in all_groups else [n for n in all_groups if n.startswith(f"{g}.")]
        for name in names:
            gs: GroupSchedule = all_groups[name]
            out[name] = {"power_now": power_now(gs, now), "days": [day_summary(d) for d in gs.days]}
        if not names:
            out[g] = {"error": "оператор не публикует график для этой очереди"}
    return {"checked_at": now.strftime("%d.%m.%Y %H:%M"), "groups": out}


def build_server(registry: Registry) -> MCPServer:
    server = MCPServer("outage-schedules", instructions=INSTRUCTIONS)
    cities = ", ".join(f"{k} ({c.name})" for k, c in registry.cities.items())
    operators = ", ".join(registry.operator_names)

    @server.tool(description=f"Определить оператора и очередь по адресу и показать график на сегодня/завтра. city: {cities}.")
    async def check_address(city: str, street: str, house: str) -> dict[str, Any]:
        if city not in registry.cities:
            return {"error": f"неизвестный город {city!r}, доступны: {cities}"}
        result = await lookup(registry, city, street, house)
        addresses = []
        for m in result.matches:
            addresses.append({
                "operator": m.operator,
                "operator_name": registry.operator_names[m.operator],
                "address": f"{registry.cities[city].name}, {m.street}, {m.house}",
                "groups": m.groups,
                **({"note": m.note} if m.note else {}),
                "schedule": await _schedules(registry, m.operator, m.groups),
            })
        return {
            "status": result.status,
            "message": LOOKUP_TEXT[result.status],
            "addresses": addresses,
            **({"suggestions": result.suggestions} if result.suggestions else {}),
            **({"unavailable_operators": [registry.operator_names[o] for o in result.unavailable]} if result.unavailable else {}),
        }

    @server.tool(description=f"График и статус «есть ли свет сейчас» для известной очереди. operator: {operators}; group: например 3.1.")
    async def get_group_schedule(operator: str, group: str) -> dict[str, Any]:
        if operator not in registry.schedules:
            return {"error": f"неизвестный оператор {operator!r}, доступны: {operators}"}
        return {"operator_name": registry.operator_names[operator], **await _schedules(registry, operator, [group])}

    @server.custom_route("/healthz", methods=["GET", "HEAD"], include_in_schema=False)
    async def healthz(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    return server


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    server = build_server(load_registry(make_client()))
    if os.getenv("MCP_TRANSPORT", "http") == "stdio":
        server.run("stdio")
        return

    import uvicorn

    secret = os.environ.get("MCP_SECRET", "")
    if len(secret) < 24:
        raise SystemExit("MCP_SECRET не задан или короче 24 символов: он защищает адрес сервера")
    hosts = [h.strip() for h in os.getenv("MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=bool(hosts), allowed_hosts=hosts, allowed_origins=[f"https://{h}" for h in hosts]
    )
    app = server.streamable_http_app(
        streamable_http_path=f"/mcp/{secret}", stateless_http=True, transport_security=security, host="0.0.0.0"
    )
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")), log_level="warning")
