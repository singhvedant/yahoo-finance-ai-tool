"""MCP server exposing Yahoo Finance data as tools for LLM agents.

Run via ``yfin serve`` (stdio or streamable-http) or
``python -m yahoo_finance_ai.mcp_server``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from yahoo_finance_ai.exceptions import YahooError
from yahoo_finance_ai.service import YahooService

logger = logging.getLogger("yahoo_finance_ai.mcp_server")

mcp = FastMCP(
    "yfinance",
    instructions=(
        "Tools for global stock market data from Yahoo Finance: symbol search, "
        "realtime quotes, OHLCV history (daily + intraday), fundamentals "
        "(income/balance/cashflow), key stats, technical indicators, dividends/"
        "splits/earnings calendar, news, option chains, holders, and analyst "
        "recommendations. Symbols use Yahoo conventions: AAPL, MSFT (US), "
        "RELIANCE.NS (NSE India), RELIANCE.BO (BSE), 7203.T (Tokyo), etc. "
        "Some endpoints need a cookie+crumb session that is bootstrapped "
        "automatically; if tools start failing with auth/rate-limit errors, "
        "call yfin_login to refresh the session (no credentials required)."
    ),
)

_service_instance: YahooService | None = None


def _service() -> YahooService:
    global _service_instance
    if _service_instance is None:
        _service_instance = YahooService()
    return _service_instance


def _error_dict(exc: Exception) -> dict[str, Any]:
    return {"error": str(exc), "error_type": type(exc).__name__}


@mcp.tool()
async def yfin_login() -> dict[str, Any]:
    """Refresh the Yahoo cookie+crumb session (no credentials needed).

    Call this if other tools return authentication or rate-limit errors —
    Yahoo sessions go stale and this self-heals them. The refreshed session
    is persisted to disk and reused by all subsequent calls.

    Returns:
        ``{"ok": bool, "crumb_present": bool}``.
    """
    try:
        return await _service().login()
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_auth_status() -> dict[str, Any]:
    """Report the current Yahoo session status.

    Returns:
        ``{"has_session": bool, "has_crumb": bool, "state_dir": str}``.
    """
    try:
        return _service().auth_status()
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_search(query: str, limit: int = 10, news: int = 5) -> dict[str, Any]:
    """Search Yahoo Finance for symbols (all world exchanges) and related news.

    Use this to resolve a company name to its Yahoo symbol before calling
    other tools, e.g. "Reliance Industries" -> RELIANCE.NS.

    Args:
        query: Company name or partial ticker.
        limit: Max symbol matches (default 10).
        news: Max news items (default 5).
    """
    try:
        result = await _service().search(query, limit=limit, news=news)
        return result.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_quote(symbols: list[str]) -> dict[str, Any]:
    """Realtime quotes for one or more symbols (price, change, market cap, P/E, 52w range).

    Args:
        symbols: Yahoo symbols, e.g. ["AAPL", "MSFT", "RELIANCE.NS"].
    """
    try:
        quotes = await _service().quote(symbols)
        return {"quotes": [q.model_dump(mode="json") for q in quotes]}
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_price(
    symbol: str, range: str = "1y", interval: str = "1d", limit: int = 0
) -> dict[str, Any]:
    """OHLCV price history — daily or intraday — with real open/high/low/close/volume.

    Args:
        symbol: Yahoo symbol, e.g. "AAPL" or "RELIANCE.NS".
        range: One of 1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max (default 1y).
        interval: One of 1m,2m,5m,15m,30m,60m,1h,1d,5d,1wk,1mo (default 1d;
            intraday intervals only work for recent ranges).
        limit: If > 0 only return the latest N candles.
    """
    try:
        history = await _service().price_history(symbol, range_=range, interval=interval)
        data = history.model_dump(mode="json")
        if limit:
            data["candles"] = data["candles"][-limit:]
        return data
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_fundamentals(
    symbol: str, statement: str = "income", frequency: str = "annual"
) -> dict[str, Any]:
    """A financial statement: income statement, balance sheet, or cash flow.

    Args:
        symbol: Yahoo symbol.
        statement: "income", "balance", or "cashflow" (default income).
        frequency: "annual" or "quarterly" (default annual).

    Returns:
        Periods (most recent first) each with end_date and raw line items.
    """
    try:
        stmt = await _service().fundamentals(symbol, statement=statement, frequency=frequency)
        return stmt.model_dump(mode="json")
    except (YahooError, ValueError) as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_key_stats(symbol: str) -> dict[str, Any]:
    """Key statistics and valuation ratios (P/E, P/B, margins, growth, debt, yields...).

    Merges Yahoo's summaryDetail, defaultKeyStatistics, and financialData modules.
    """
    try:
        ks = await _service().key_stats(symbol)
        return ks.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_profile(symbol: str) -> dict[str, Any]:
    """Company profile: name, sector, industry, country, employees, business summary."""
    try:
        p = await _service().profile(symbol)
        return p.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_technical(
    symbol: str, range: str = "1y", include_series: bool = False
) -> dict[str, Any]:
    """Technical analysis: SMA/EMA(20,50,100,200), RSI14, MACD, Bollinger, ATR14, Stochastic + signals.

    Args:
        symbol: Yahoo symbol.
        range: Price history window the analysis is based on (default 1y).
        include_series: If True include full date-aligned indicator series (large).

    Returns:
        Snapshot of latest values plus qualitative signals like
        ``{"rsi": "neutral", "macd": "bullish_crossover", "trend": "above_sma200"}``.
    """
    try:
        analysis = await _service().technical(symbol, range_=range, include_series=include_series)
        return analysis.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_events(symbol: str, range: str = "5y") -> dict[str, Any]:
    """Corporate events: dividend history, stock splits, earnings calendar, ex-dividend date.

    Args:
        symbol: Yahoo symbol.
        range: How far back to fetch dividends/splits (default 5y).
    """
    try:
        ev = await _service().events(symbol, range_=range)
        return ev.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_earnings(symbol: str) -> dict[str, Any]:
    """Earnings: history of actual vs estimated EPS, quarterly revenue/earnings, next earnings dates."""
    try:
        ed = await _service().earnings(symbol)
        return ed.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_news(symbol: str, limit: int = 10) -> dict[str, Any]:
    """Recent Yahoo Finance news headlines for a ticker (title, publisher, link, time)."""
    try:
        items = await _service().news(symbol, limit=limit)
        return {"symbol": symbol, "news": [n.model_dump(mode="json") for n in items]}
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_options(symbol: str, expiry: str = "") -> dict[str, Any]:
    """Option chain: calls and puts with strikes, bid/ask, volume, open interest, IV.

    Args:
        symbol: Yahoo symbol (options mostly available for US tickers).
        expiry: Expiry date "YYYY-MM-DD"; empty = nearest expiry. The response
            lists all available expirations.
    """
    try:
        chain = await _service().options(symbol, expiry=expiry or None)
        return chain.model_dump(mode="json")
    except (YahooError, ValueError) as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_holders(symbol: str) -> dict[str, Any]:
    """Ownership: insider/institutional percentage breakdown + top institutional and fund holders."""
    try:
        hd = await _service().holders(symbol)
        return hd.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_analysts(symbol: str) -> dict[str, Any]:
    """Analyst data: price targets (mean/high/low), consensus rating, recommendation trend, recent upgrades/downgrades."""
    try:
        ad = await _service().analysts(symbol)
        return ad.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_snapshot(symbol: str) -> dict[str, Any]:
    """Full snapshot in one call: quote, profile, key stats, events, analysts, technicals, news.

    Larger than individual tools — use for one-shot comprehensive research.
    Per-part failures are tolerated (missing parts come back null).
    """
    try:
        snap = await _service().snapshot(symbol)
        return snap.model_dump(mode="json")
    except YahooError as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_bulk(
    symbols: list[str], dataset: str = "price", range: str = "1y", concurrency: int = 8
) -> dict[str, Any]:
    """Fetch the same dataset for many symbols concurrently with per-symbol error isolation.

    Args:
        symbols: Yahoo symbols (mix of exchanges fine).
        dataset: "price", "quote", "technical", "fundamentals", "key_stats", or "snapshot".
        range: Price-history window where applicable (default 1y).
        concurrency: Max concurrent requests (default 8).

    Returns:
        ``{"results": {symbol: data | {"error": str}}}`` — failures never abort the batch.
    """
    from yahoo_finance_ai.bulk import bulk_fetch

    try:
        results = await bulk_fetch(
            _service(), symbols, dataset=dataset, range_=range, concurrency=concurrency
        )
        dumped: dict[str, Any] = {}
        for symbol, value in results.items():
            dumped[symbol] = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        return {"results": dumped}
    except (YahooError, ValueError) as exc:
        return _error_dict(exc)


@mcp.tool()
async def yfin_export(
    symbol: str, what: str = "snapshot", fmt: str = "json", out_path: str = ""
) -> dict[str, Any]:
    """Export a symbol's data to a file on disk (JSON, CSV, or parquet).

    Args:
        symbol: Yahoo symbol.
        what: "price", "fundamentals", "snapshot", or "options".
        fmt: "json", "csv", or "parquet".
        out_path: Destination path; default "<symbol>_<what>.<fmt>" in cwd.

    Returns:
        ``{"path": str}``.
    """
    from yahoo_finance_ai.export import export_data

    service = _service()
    try:
        if what == "price":
            data: Any = await service.price_history(symbol)
        elif what == "fundamentals":
            data = await service.fundamentals(symbol)
        elif what == "snapshot":
            data = await service.snapshot(symbol)
        elif what == "options":
            data = await service.options(symbol)
        else:
            return {
                "error": f"Invalid what={what!r}; expected price, fundamentals, snapshot, or options",
                "error_type": "ValueError",
            }
        path = Path(out_path) if out_path else Path(f"{symbol}_{what}.{fmt}")
        result_path = export_data(data, path, fmt=fmt)  # type: ignore[arg-type]
        return {"path": str(result_path)}
    except (YahooError, ValueError) as exc:
        return _error_dict(exc)


def run_stdio() -> None:
    """Run the MCP server over stdio (for MCP client subprocesses)."""
    mcp.run(transport="stdio")


def run_http(host: str = "127.0.0.1", port: int = 8632) -> None:
    """Run the MCP server over streamable HTTP at ``http://host:port/mcp``."""
    mcp.settings.host = host
    mcp.settings.port = port
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    run_stdio()
