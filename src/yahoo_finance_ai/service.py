"""High-level service facade — the only layer the CLI and MCP server call."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Any

from . import indicators, parsers
from .auth import has_session
from .client import YahooClient
from .exceptions import YahooError
from .models import (
    AnalystData,
    CompanyProfile,
    CorporateEvents,
    EarningsData,
    FinancialStatement,
    FullSnapshot,
    HoldersData,
    KeyStats,
    NewsItem,
    OptionChain,
    PriceHistory,
    Quote,
    SearchResult,
    TechnicalAnalysis,
)

logger = logging.getLogger("yahoo_finance_ai.service")

_STATEMENT_MODULES = {
    ("income", "annual"): "incomeStatementHistory",
    ("income", "quarterly"): "incomeStatementHistoryQuarterly",
    ("balance", "annual"): "balanceSheetHistory",
    ("balance", "quarterly"): "balanceSheetHistoryQuarterly",
    ("cashflow", "annual"): "cashflowStatementHistory",
    ("cashflow", "quarterly"): "cashflowStatementHistoryQuarterly",
}

DEFAULT_MODULES: dict[str, list[str]] = {
    "key_stats": ["summaryDetail", "defaultKeyStatistics", "financialData"],
    "profile": ["summaryProfile", "price"],
    "analysts": ["financialData", "recommendationTrend", "upgradeDowngradeHistory"],
    "holders": ["majorHoldersBreakdown", "institutionOwnership", "fundOwnership"],
    "earnings": ["earningsHistory", "earnings", "calendarEvents"],
    "events": ["calendarEvents", "summaryDetail"],
}

_CACHE_MAX = 16


class YahooService:
    """Facade over :class:`YahooClient` + parsers + indicators."""

    def __init__(self, client: YahooClient | None = None) -> None:
        self.client = client or YahooClient()
        self._summary_cache: dict[tuple[str, frozenset[str]], dict] = {}

    async def __aenter__(self) -> YahooService:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self.client.aclose()

    # ----------------------------------------------------------------- auth

    async def login(self) -> dict:
        ok = await self.client.refresh_session()
        return {"ok": ok, "crumb_present": self.client.has_crumb}

    def auth_status(self) -> dict:
        return {
            "has_session": has_session(self.client.store),
            "has_crumb": self.client.has_crumb,
            "state_dir": str(self.client.store.state_dir),
        }

    def logout(self) -> dict:
        self.client.logout()
        return {"ok": True}

    # ------------------------------------------------------------- internal

    async def _summary(self, symbol: str, modules: list[str]) -> dict:
        key = (symbol.upper(), frozenset(modules))
        if key in self._summary_cache:
            return self._summary_cache[key]
        result = await self.client.quote_summary(symbol, modules)
        if len(self._summary_cache) >= _CACHE_MAX:
            self._summary_cache.pop(next(iter(self._summary_cache)))
        self._summary_cache[key] = result
        return result

    # --------------------------------------------------------------- public

    async def search(self, query: str, limit: int = 10, news: int = 5) -> SearchResult:
        payload = await self.client.search_raw(query, quotes_count=limit, news_count=news)
        result = parsers.parse_search(payload, query)
        result.quotes = result.quotes[:limit]
        result.news = result.news[:news]
        return result

    async def quote(self, symbols: list[str]) -> list[Quote]:
        raw = await self.client.quotes_raw(symbols)
        return [parsers.parse_quote(item) for item in raw]

    async def price_history(
        self, symbol: str, range_: str = "1y", interval: str = "1d"
    ) -> PriceHistory:
        payload = await self.client.chart(symbol, range_=range_, interval=interval)
        return parsers.parse_chart(payload)

    async def fundamentals(
        self, symbol: str, statement: str = "income", frequency: str = "annual"
    ) -> FinancialStatement:
        key = (statement, frequency)
        if key not in _STATEMENT_MODULES:
            raise ValueError(
                f"Invalid statement={statement!r}/frequency={frequency!r}; "
                "statement must be income|balance|cashflow, frequency annual|quarterly"
            )
        module_name = _STATEMENT_MODULES[key]
        result = await self._summary(symbol, [module_name])
        return parsers.parse_statement(
            result.get(module_name) or {}, symbol, statement, frequency
        )

    async def key_stats(self, symbol: str) -> KeyStats:
        result = await self._summary(symbol, DEFAULT_MODULES["key_stats"])
        return parsers.parse_key_stats(result, symbol)

    async def profile(self, symbol: str) -> CompanyProfile:
        result = await self._summary(symbol, DEFAULT_MODULES["profile"])
        return parsers.parse_profile(
            result.get("summaryProfile") or {}, symbol, price=result.get("price")
        )

    async def technical(
        self, symbol: str, range_: str = "1y", include_series: bool = False
    ) -> TechnicalAnalysis:
        history = await self.price_history(symbol, range_=range_, interval="1d")
        return indicators.compute_analysis(history, include_series=include_series)

    async def events(self, symbol: str, range_: str = "5y") -> CorporateEvents:
        chart_payload, summary = await asyncio.gather(
            self.client.chart(symbol, range_=range_, interval="1mo", events="div,splits"),
            self._summary(symbol, DEFAULT_MODULES["events"]),
            return_exceptions=True,
        )
        if isinstance(chart_payload, BaseException):
            raise chart_payload
        calendar = summary_detail = None
        if not isinstance(summary, BaseException):
            calendar = summary.get("calendarEvents")
            summary_detail = summary.get("summaryDetail")
        else:
            logger.warning("events: quoteSummary failed for %s: %s", symbol, summary)
        return parsers.parse_events(chart_payload, calendar, summary_detail)

    async def earnings(self, symbol: str) -> EarningsData:
        result = await self._summary(symbol, DEFAULT_MODULES["earnings"])
        return parsers.parse_earnings(result, symbol)

    async def news(self, symbol: str, limit: int = 10) -> list[NewsItem]:
        # Yahoo's search-news endpoint often returns generic/unrelated global
        # headlines for non-US tickers (e.g. AUBANK.NS). Over-fetch and keep
        # only items whose relatedTickers actually reference this symbol.
        payload = await self.client.search_raw(
            symbol, quotes_count=1, news_count=max(limit * 5, 25)
        )
        items = parsers.parse_news(payload)
        base = symbol.split(".")[0].upper()
        relevant = [
            n
            for n in items
            if any(t.upper() in (symbol.upper(), base) for t in n.related_tickers)
        ]
        return relevant[:limit]

    async def options(self, symbol: str, expiry: str | None = None) -> OptionChain:
        date_param: int | None = None
        if expiry:
            d = dt.date.fromisoformat(expiry)
            date_param = int(
                dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp()
            )
        result = await self.client.options_raw(symbol, date=date_param)
        return parsers.parse_options(result)

    async def holders(self, symbol: str) -> HoldersData:
        result = await self._summary(symbol, DEFAULT_MODULES["holders"])
        return parsers.parse_holders(result, symbol)

    async def analysts(self, symbol: str) -> AnalystData:
        result = await self._summary(symbol, DEFAULT_MODULES["analysts"])
        return parsers.parse_analysts(result, symbol)

    async def snapshot(self, symbol: str) -> FullSnapshot:
        """Everything about a symbol in one call; per-part failures tolerated."""

        async def _part(coro: Any) -> Any:
            try:
                return await coro
            except (YahooError, ValueError) as exc:
                logger.warning("snapshot part failed for %s: %s", symbol, exc)
                return None

        quote_list, profile, key_stats, events, analysts, technical, news = (
            await asyncio.gather(
                _part(self.quote([symbol])),
                _part(self.profile(symbol)),
                _part(self.key_stats(symbol)),
                _part(self.events(symbol)),
                _part(self.analysts(symbol)),
                _part(self.technical(symbol)),
                _part(self.news(symbol, limit=5)),
            )
        )
        return FullSnapshot(
            symbol=symbol,
            quote=quote_list[0] if quote_list else None,
            profile=profile,
            key_stats=key_stats,
            events=events,
            analysts=analysts,
            technical=technical.snapshot if technical else None,
            news=news or [],
        )
