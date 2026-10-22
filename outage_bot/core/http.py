import asyncio
import random
import time
from collections.abc import Awaitable, Callable

import httpx

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


class SourceUnavailable(Exception):
    """Источник не ответил (сеть, таймаут, 5xx)."""


class SourceSchemaError(Exception):
    """Источник ответил, но формат не совпал с ожидаемым."""


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(15.0),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


async def request(
    client: httpx.AsyncClient, method: str, url: str, *, retries: int = 3, ok_statuses: tuple[int, ...] = (), **kw
) -> httpx.Response:
    for attempt in range(retries):
        try:
            resp = await client.request(method, url, **kw)
            if resp.status_code < 400 or resp.status_code in ok_statuses:
                return resp
            if resp.status_code < 500 and resp.status_code != 429:
                raise SourceUnavailable(f"{url}: HTTP {resp.status_code}")
        except httpx.TransportError as exc:
            if attempt == retries - 1:
                raise SourceUnavailable(f"{url}: {exc!r}") from exc
        if attempt < retries - 1:
            await asyncio.sleep(0.5 * 2**attempt + random.uniform(0, 0.3))
    raise SourceUnavailable(f"{url}: HTTP {resp.status_code}")


class TTLCache:
    """Кэш одного значения: один запрос к источнику на всех пользователей за ttl секунд."""

    def __init__(self, ttl: float):
        self.ttl = ttl
        self._value = None
        self._at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, load: Callable[[], Awaitable]):
        async with self._lock:
            if self._value is None or time.monotonic() - self._at > self.ttl:
                self._value = await load()
                self._at = time.monotonic()
            return self._value
