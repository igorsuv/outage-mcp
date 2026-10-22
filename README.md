# Графики отключений света — MCP-сервер

Отвечает в чате Claude (в том числе с телефона) на вопросы вида «есть ли свет на Олександра Поля 18?».
Города: Дніпро (ДТЕК ДнЕМ, ЦЕК), Покров (ДТЕК ДнЕМ), Запоріжжя (Запоріжжяобленерго).
Оператор и очередь определяются по адресу автоматически. LLM/платных API в рантайме нет.

Тулы: `check_address(city, street, house)`, `get_group_schedule(operator, group)`.

| Оператор | Адрес → очередь | График |
|---|---|---|
| ДТЕК ДнЕМ | YASNO `addresses/v2/*` | YASNO `dsos/301/planned-outages` |
| ЦЕК | cek.dp.ua, «Визначення черги» | YASNO `dsos/303/planned-outages` |
| Запоріжжяобленерго | Google Sheets ЗОЕ (gviz CSV) | посты zoe.com.ua/outage/ |

Города и операторы — в `outage_bot/config/cities.yaml`.

## Локально

```bash
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

## Деплой

```bash
docker build -t outage-mcp .
docker run -d --restart unless-stopped -p 8000:8000 -e MCP_SECRET=<секрет> -e MCP_ALLOWED_HOSTS=<домен> outage-mcp
```

Нужен HTTPS (reverse proxy или хостинг с TLS). Адрес сервера: `https://<домен>/mcp/<MCP_SECRET>` — держите его в секрете.

## Подключение к Claude

claude.ai → Settings → Connectors → Add custom connector → вставить адрес сервера.
После этого коннектор доступен и в мобильном приложении Claude.
