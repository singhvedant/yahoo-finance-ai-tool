"""Async Yahoo Finance client.

CRITICAL: Yahoo blocks non-browser TLS fingerprints — plain httpx/curl get
HTTP 429 on every ``query{1,2}.finance.yahoo.com`` endpoint regardless of
headers. The transport therefore MUST be ``curl_cffi`` with
``impersonate="chrome"`` (verified live 2026-06-12).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from pathlib import Path
from typing import Any

from curl_cffi.requests import AsyncSession

from . import auth as auth_mod
from .exceptions import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    YahooError,
)

logger = logging.getLogger("yahoo_finance_ai.client")


class RateLimiter:
    """Async token-bucket rate limiter."""

    def __init__(self, rate: float = 2.0, burst: int = 4) -> None:
        self.rate = rate
        self.burst = burst
        self._tokens = float(burst)
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self.rate
                await asyncio.sleep(wait)


def _cookies_dict(session: AsyncSession) -> dict[str, str]:
    jar = getattr(session.cookies, "jar", None)
    if jar is not None:
        return {c.name: c.value for c in jar if c.value is not None}
    try:
        return dict(session.cookies)
    except Exception:  # noqa: BLE001
        return {}


class YahooClient:
    """Rate-limited, retrying async client for Yahoo's unofficial finance API."""

    Q1 = "https://query1.finance.yahoo.com"
    Q2 = "https://query2.finance.yahoo.com"

    def __init__(
        self,
        state_dir: Path | None = None,
        rate: float = 2.0,
        burst: int = 4,
        max_retries: int = 3,
        timeout: float = 20.0,
    ) -> None:
        self.store = auth_mod.SessionStore(state_dir)
        self.timeout = timeout
        self.max_retries = max_retries
        self.limiter = RateLimiter(rate=rate, burst=burst)
        self.crumb: str | None = None
        self.session = AsyncSession(
            impersonate="chrome",
            timeout=timeout,
            headers={"Accept": "application/json, text/plain, */*"},
        )
        self._bootstrap_lock = asyncio.Lock()
        self._load_persisted()

    # ------------------------------------------------------------ lifecycle

    def _load_persisted(self) -> None:
        data = self.store.load()
        if not data:
            return
        for name, value in (data.get("cookies") or {}).items():
            try:
                self.session.cookies.set(name, value, domain=".yahoo.com")
            except Exception:  # noqa: BLE001
                logger.debug("Could not restore cookie %s", name)
        self.crumb = data.get("crumb") or None
        if self.crumb:
            logger.debug("Restored persisted Yahoo session")

    async def __aenter__(self) -> YahooClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.session.close()

    @property
    def has_crumb(self) -> bool:
        return bool(self.crumb)

    # ----------------------------------------------------------------- auth

    async def refresh_session(self) -> bool:
        """(Re-)bootstrap the cookie+crumb session. True on success."""
        async with self._bootstrap_lock:
            try:
                await auth_mod.bootstrap_session(self)
                return True
            except AuthenticationError as exc:
                logger.warning("Session bootstrap failed: %s", exc)
                return False

    def logout(self) -> None:
        self.store.clear()
        self.crumb = None
        try:
            self.session.cookies.clear()
        except Exception:  # noqa: BLE001
            pass

    def _persist_cookies(self) -> None:
        if self.crumb:
            self.store.save(_cookies_dict(self.session), self.crumb)

    # -------------------------------------------------------------- request

    async def get_json(
        self, url: str, params: dict | None = None, need_crumb: bool = False
    ) -> Any:
        """Central request path: rate-limit, crumb injection, retry, error mapping."""
        if need_crumb and not self.crumb:
            ok = await self.refresh_session()
            if not ok:
                raise AuthenticationError(
                    "No Yahoo session and bootstrap failed; try `yfin login` again later."
                )

        params = dict(params or {})
        if need_crumb and self.crumb:
            params["crumb"] = self.crumb

        refreshed = False
        last_exc: Exception | None = None
        attempt = 0
        while attempt <= self.max_retries:
            await self.limiter.acquire()
            try:
                resp = await self.session.get(url, params=params, timeout=self.timeout)
            except Exception as exc:  # noqa: BLE001 - curl transport errors
                last_exc = exc
                attempt += 1
                if attempt > self.max_retries:
                    raise YahooError(f"Transport error for {url}: {exc}") from exc
                await self._backoff(attempt)
                continue

            status = resp.status_code
            if status == 200:
                try:
                    return resp.json()
                except Exception as exc:  # noqa: BLE001
                    raise YahooError(f"Non-JSON response from {url}") from exc

            if status == 404:
                raise NotFoundError(f"Not found: {url} (symbol may be invalid or delisted)")

            body_head = (resp.text or "")[:200]
            if status in (401, 403) or "Invalid Crumb" in body_head:
                if not refreshed:
                    refreshed = True
                    logger.info("Got HTTP %s — refreshing Yahoo session and retrying", status)
                    if await self.refresh_session():
                        if need_crumb and self.crumb:
                            params["crumb"] = self.crumb
                        continue
                raise AuthenticationError(
                    f"Yahoo rejected the session (HTTP {status}) and refresh did not help."
                )

            if status == 429 or status >= 500:
                attempt += 1
                if attempt > self.max_retries:
                    if status == 429:
                        retry_after = None
                        try:
                            retry_after = float(resp.headers.get("retry-after", ""))
                        except (TypeError, ValueError):
                            pass
                        raise RateLimitError(
                            "Yahoo rate limited this client (HTTP 429) after retries.",
                            retry_after=retry_after,
                        )
                    raise YahooError(f"Yahoo server error HTTP {status} for {url}")
                await self._backoff(attempt)
                continue

            raise YahooError(f"Unexpected HTTP {status} from {url}: {body_head}")

        raise YahooError(f"Request failed after retries: {url} ({last_exc})")

    async def _backoff(self, attempt: int) -> None:
        delay = min(30.0, (2.0**attempt) + random.uniform(0, 0.5))
        logger.debug("Backing off %.1fs (attempt %d)", delay, attempt)
        await asyncio.sleep(delay)

    # ---------------------------------------------------- endpoint wrappers

    async def chart(
        self,
        symbol: str,
        range_: str = "1y",
        interval: str = "1d",
        events: str = "div,splits",
    ) -> dict:
        payload = await self.get_json(
            f"{self.Q1}/v8/finance/chart/{symbol}",
            params={"range": range_, "interval": interval, "events": events},
        )
        result = (payload.get("chart") or {}).get("result")
        if not result:
            err = ((payload.get("chart") or {}).get("error") or {}).get("description")
            raise NotFoundError(f"No chart data for {symbol}: {err or 'empty result'}")
        return payload

    async def search_raw(self, query: str, quotes_count: int = 10, news_count: int = 10) -> dict:
        return await self.get_json(
            f"{self.Q1}/v1/finance/search",
            params={"q": query, "quotesCount": quotes_count, "newsCount": news_count},
        )

    async def quote_summary(self, symbol: str, modules: list[str]) -> dict:
        payload = await self.get_json(
            f"{self.Q2}/v10/finance/quoteSummary/{symbol}",
            params={"modules": ",".join(modules)},
            need_crumb=True,
        )
        result = (payload.get("quoteSummary") or {}).get("result")
        if not result:
            err = ((payload.get("quoteSummary") or {}).get("error") or {}).get("description")
            raise NotFoundError(f"No quoteSummary data for {symbol}: {err or 'empty result'}")
        return result[0]

    async def quotes_raw(self, symbols: list[str]) -> list[dict]:
        payload = await self.get_json(
            f"{self.Q1}/v7/finance/quote",
            params={"symbols": ",".join(symbols)},
            need_crumb=True,
        )
        return ((payload.get("quoteResponse") or {}).get("result")) or []

    async def options_raw(self, symbol: str, date: int | None = None) -> dict:
        params: dict[str, Any] = {}
        if date is not None:
            params["date"] = date
        payload = await self.get_json(
            f"{self.Q1}/v7/finance/options/{symbol}", params=params, need_crumb=True
        )
        result = (payload.get("optionChain") or {}).get("result")
        if not result:
            raise NotFoundError(f"No option chain for {symbol}")
        return result[0]
