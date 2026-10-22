FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Europe/Kyiv
WORKDIR /app

COPY pyproject.toml ./
COPY outage_bot ./outage_bot
RUN pip install --no-cache-dir .

RUN useradd --create-home app
USER app

EXPOSE 8000
CMD ["python", "-m", "outage_bot.mcp_server"]
