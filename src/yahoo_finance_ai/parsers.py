"""Pure parsing functions: raw Yahoo JSON dicts -> pydantic models.

Grounded in live-probed fixtures under ``tests/fixtures/`` (2026-06-12).
quoteSummary numeric values arrive wrapped as ``{"raw": x, "fmt": "..."}``
(sometimes plain, sometimes ``{}`` meaning missing) — everything routes
through :func:`unwrap`. Chart/options/v7-quote use plain numbers.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from .models import (
    AnalystData,
    Candle,
    CompanyProfile,
    CorporateEvents,
    DividendEvent,
    EarningsData,
    EarningsDates,
    EarningsPeriod,
    FinancialStatement,
    HoldersData,
    InstitutionalHolder,
    KeyStats,
    MajorHoldersBreakdown,
    NewsItem,
    OptionChain,
    OptionContract,
    PriceHistory,
    PriceTarget,
    Quote,
    RecommendationTrend,
    SearchQuote,
    SearchResult,
    SplitEvent,
    StatementPeriod,
)

logger = logging.getLogger("yahoo_finance_ai.parsers")


def unwrap(v: Any) -> Any:
    """``{"raw": x, ...}`` -> ``x``; ``{}`` -> ``None``; passthrough otherwise."""
    if isinstance(v, dict):
        if "raw" in v:
            return v["raw"]
        if not v:
            return None
        return v
    return v


def to_date(value: Any) -> dt.date | None:
    """Epoch int/float, ISO string, or None -> date."""
    value = unwrap(value)
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return dt.datetime.fromtimestamp(value, dt.timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _f(v: Any) -> float | None:
    v = unwrap(v)
    if isinstance(v, bool) or v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v: Any) -> int | None:
    v = _f(v)
    return int(v) if v is not None else None


# -------------------------------------------------------------- search/news


def parse_news(payload: dict) -> list[NewsItem]:
    items: list[NewsItem] = []
    for n in payload.get("news") or []:
        title = n.get("title")
        if not title:
            continue
        published = None
        ts = n.get("providerPublishTime")
        if isinstance(ts, (int, float)):
            published = dt.datetime.fromtimestamp(ts, dt.timezone.utc)
        items.append(
            NewsItem(
                uuid=n.get("uuid"),
                title=title,
                publisher=n.get("publisher"),
                link=n.get("link"),
                published=published,
                related_tickers=n.get("relatedTickers") or [],
            )
        )
    return items


def parse_search(payload: dict, query: str) -> SearchResult:
    quotes: list[SearchQuote] = []
    for q in payload.get("quotes") or []:
        symbol = q.get("symbol")
        if not symbol:
            continue
        quotes.append(
            SearchQuote(
                symbol=symbol,
                name=q.get("longname") or q.get("shortname"),
                exchange=q.get("exchange"),
                exch_disp=q.get("exchDisp"),
                quote_type=q.get("quoteType"),
                score=_f(q.get("score")),
            )
        )
    return SearchResult(query=query, quotes=quotes, news=parse_news(payload))


# --------------------------------------------------------------------- quote


def parse_quote(item: dict) -> Quote:
    known = {
        "symbol",
        "longName",
        "shortName",
        "currency",
        "fullExchangeName",
        "exchange",
        "marketState",
        "regularMarketPrice",
        "regularMarketChange",
        "regularMarketChangePercent",
        "regularMarketPreviousClose",
        "regularMarketDayHigh",
        "regularMarketDayLow",
        "regularMarketVolume",
        "marketCap",
        "trailingPE",
        "forwardPE",
        "epsTrailingTwelveMonths",
        "fiftyTwoWeekHigh",
        "fiftyTwoWeekLow",
        "dividendYield",
    }
    extras = {
        k: v
        for k, v in item.items()
        if k not in known and isinstance(v, (int, float, str, bool))
    }
    return Quote(
        symbol=item.get("symbol", ""),
        name=item.get("longName") or item.get("shortName"),
        currency=item.get("currency"),
        exchange=item.get("fullExchangeName") or item.get("exchange"),
        market_state=item.get("marketState"),
        price=_f(item.get("regularMarketPrice")),
        change=_f(item.get("regularMarketChange")),
        change_pct=_f(item.get("regularMarketChangePercent")),
        previous_close=_f(item.get("regularMarketPreviousClose")),
        day_high=_f(item.get("regularMarketDayHigh")),
        day_low=_f(item.get("regularMarketDayLow")),
        volume=_i(item.get("regularMarketVolume")),
        market_cap=_f(item.get("marketCap")),
        trailing_pe=_f(item.get("trailingPE")),
        forward_pe=_f(item.get("forwardPE")),
        eps_ttm=_f(item.get("epsTrailingTwelveMonths")),
        high_52w=_f(item.get("fiftyTwoWeekHigh")),
        low_52w=_f(item.get("fiftyTwoWeekLow")),
        dividend_yield=_f(item.get("dividendYield")),
        extras=extras,
    )


# --------------------------------------------------------------------- chart


def parse_chart(payload: dict) -> PriceHistory:
    result = payload["chart"]["result"][0]
    meta = result.get("meta") or {}
    timestamps = result.get("timestamp") or []
    indicators = result.get("indicators") or {}
    quote = (indicators.get("quote") or [{}])[0] or {}
    adj = (indicators.get("adjclose") or [{}])[0] or {}

    opens = quote.get("open") or []
    highs = quote.get("high") or []
    lows = quote.get("low") or []
    closes = quote.get("close") or []
    volumes = quote.get("volume") or []
    adjcloses = adj.get("adjclose") or []

    candles: list[Candle] = []
    for i, ts in enumerate(timestamps):
        def at(arr: list) -> Any:
            return arr[i] if i < len(arr) else None

        vol = at(volumes)
        candles.append(
            Candle(
                ts=dt.datetime.fromtimestamp(ts, dt.timezone.utc),
                open=_f(at(opens)),
                high=_f(at(highs)),
                low=_f(at(lows)),
                close=_f(at(closes)),
                volume=int(vol) if isinstance(vol, (int, float)) else None,
                adj_close=_f(at(adjcloses)),
            )
        )

    return PriceHistory(
        symbol=meta.get("symbol", ""),
        currency=meta.get("currency"),
        timezone=meta.get("exchangeTimezoneName") or meta.get("timezone"),
        interval=meta.get("dataGranularity") or "1d",
        range=meta.get("range") or "",
        candles=candles,
    )


# -------------------------------------------------------------------- events


def parse_events(
    payload: dict, calendar: dict | None = None, summary_detail: dict | None = None
) -> CorporateEvents:
    result = payload["chart"]["result"][0]
    meta = result.get("meta") or {}
    events = result.get("events") or {}

    dividends = sorted(
        (
            DividendEvent(date=d, amount=amount)
            for v in (events.get("dividends") or {}).values()
            if (d := to_date(v.get("date"))) is not None
            and (amount := _f(v.get("amount"))) is not None
        ),
        key=lambda e: e.date,
    )
    splits = sorted(
        (
            SplitEvent(
                date=d,
                numerator=_f(v.get("numerator")) or 0.0,
                denominator=_f(v.get("denominator")) or 1.0,
                ratio=v.get("splitRatio") or "",
            )
            for v in (events.get("splits") or {}).values()
            if (d := to_date(v.get("date"))) is not None
        ),
        key=lambda e: e.date,
    )

    cal_model: EarningsDates | None = None
    if calendar:
        earnings = calendar.get("earnings") or {}
        cal_model = EarningsDates(
            earnings_dates=[
                d for raw in (earnings.get("earningsDate") or []) if (d := to_date(raw))
            ],
            is_estimate=earnings.get("isEarningsDateEstimate"),
            eps_avg=_f(earnings.get("earningsAverage")),
            eps_low=_f(earnings.get("earningsLow")),
            eps_high=_f(earnings.get("earningsHigh")),
            revenue_avg=_f(earnings.get("revenueAverage")),
        )

    ex_div = div_date = None
    if summary_detail:
        ex_div = to_date(summary_detail.get("exDividendDate"))
        div_date = to_date(summary_detail.get("dividendDate"))
    if calendar and not ex_div:
        ex_div = to_date(calendar.get("exDividendDate"))
    if calendar and not div_date:
        div_date = to_date(calendar.get("dividendDate"))

    return CorporateEvents(
        symbol=meta.get("symbol", ""),
        dividends=dividends,
        splits=splits,
        calendar=cal_model,
        ex_dividend_date=ex_div,
        dividend_date=div_date,
    )


# -------------------------------------------------------------- fundamentals

_STATEMENT_SKIP_KEYS = {"maxAge", "endDate"}


def parse_statement(module: dict, symbol: str, kind: str, frequency: str) -> FinancialStatement:
    """``module`` is e.g. ``quoteSummary result[0]["incomeStatementHistory"]``.

    The inner list lives under the key matching the module's base name
    (e.g. ``incomeStatementHistory`` for both annual and quarterly modules).
    """
    inner: list[dict] = []
    for key, value in (module or {}).items():
        if isinstance(value, list):
            inner = value
            break

    periods: list[StatementPeriod] = []
    for entry in inner:
        items: dict[str, float | None] = {}
        for k, v in entry.items():
            if k in _STATEMENT_SKIP_KEYS:
                continue
            items[k] = _f(v)
        periods.append(
            StatementPeriod(
                end_date=to_date(entry.get("endDate")),
                period_type="12M" if frequency == "annual" else "3M",
                items=items,
            )
        )

    return FinancialStatement(
        symbol=symbol,
        kind=kind,  # type: ignore[arg-type]
        frequency=frequency,  # type: ignore[arg-type]
        currency=None,
        periods=periods,
    )


def parse_key_stats(result: dict, symbol: str) -> KeyStats:
    stats: dict[str, float | str | bool | None] = {}
    for module_name in ("summaryDetail", "defaultKeyStatistics", "financialData"):
        module = result.get(module_name) or {}
        for k, v in module.items():
            if k == "maxAge":
                continue
            val = unwrap(v)
            if isinstance(val, (int, float, str, bool)) or val is None:
                stats[k] = val
    return KeyStats(symbol=symbol, stats=stats)


def parse_profile(module: dict, symbol: str, price: dict | None = None) -> CompanyProfile:
    module = module or {}
    name = None
    if price:
        name = unwrap(price.get("longName")) or unwrap(price.get("shortName"))
    return CompanyProfile(
        symbol=symbol,
        name=name,
        sector=module.get("sector"),
        industry=module.get("industry"),
        website=module.get("website"),
        country=module.get("country"),
        employees=_i(module.get("fullTimeEmployees")),
        summary=module.get("longBusinessSummary"),
    )


# ------------------------------------------------------------------ analysts


def parse_analysts(result: dict, symbol: str) -> AnalystData:
    fin = result.get("financialData") or {}
    target = PriceTarget(
        current=_f(fin.get("currentPrice")),
        mean=_f(fin.get("targetMeanPrice")),
        high=_f(fin.get("targetHighPrice")),
        low=_f(fin.get("targetLowPrice")),
        median=_f(fin.get("targetMedianPrice")),
        analysts=_i(fin.get("numberOfAnalystOpinions")),
        recommendation_key=fin.get("recommendationKey"),
        recommendation_mean=_f(fin.get("recommendationMean")),
    )

    trend = [
        RecommendationTrend(
            period=t.get("period", ""),
            strong_buy=_i(t.get("strongBuy")) or 0,
            buy=_i(t.get("buy")) or 0,
            hold=_i(t.get("hold")) or 0,
            sell=_i(t.get("sell")) or 0,
            strong_sell=_i(t.get("strongSell")) or 0,
        )
        for t in ((result.get("recommendationTrend") or {}).get("trend") or [])
    ]

    upgrades: list[dict[str, Any]] = []
    for u in ((result.get("upgradeDowngradeHistory") or {}).get("history") or [])[:20]:
        upgrades.append(
            {
                "firm": u.get("firm"),
                "to_grade": u.get("toGrade"),
                "from_grade": u.get("fromGrade"),
                "action": u.get("action"),
                "date": str(to_date(u.get("epochGradeDate")) or ""),
            }
        )

    return AnalystData(
        symbol=symbol,
        price_target=target if any(v is not None for v in target.model_dump().values()) else None,
        trend=trend,
        upgrades=upgrades,
    )


# ------------------------------------------------------------------- holders


def _parse_ownership_list(module: dict | None) -> list[InstitutionalHolder]:
    holders: list[InstitutionalHolder] = []
    for h in (module or {}).get("ownershipList") or []:
        org = h.get("organization")
        if not org:
            continue
        holders.append(
            InstitutionalHolder(
                organization=org,
                pct_held=_f(h.get("pctHeld")),
                position=_f(h.get("position")),
                value=_f(h.get("value")),
                report_date=to_date(h.get("reportDate")),
            )
        )
    return holders


def parse_holders(result: dict, symbol: str) -> HoldersData:
    mhb = result.get("majorHoldersBreakdown") or {}
    breakdown = MajorHoldersBreakdown(
        insiders_pct=_f(mhb.get("insidersPercentHeld")),
        institutions_pct=_f(mhb.get("institutionsPercentHeld")),
        institutions_float_pct=_f(mhb.get("institutionsFloatPercentHeld")),
        institutions_count=_i(mhb.get("institutionsCount")),
    )
    has_breakdown = any(v is not None for v in breakdown.model_dump().values())
    return HoldersData(
        symbol=symbol,
        breakdown=breakdown if has_breakdown else None,
        institutional=_parse_ownership_list(result.get("institutionOwnership")),
        funds=_parse_ownership_list(result.get("fundOwnership")),
    )


# ------------------------------------------------------------------ earnings


def parse_earnings(result: dict, symbol: str) -> EarningsData:
    history = [
        EarningsPeriod(
            period=h.get("period"),
            date=to_date(h.get("quarter")),
            eps_actual=_f(h.get("epsActual")),
            eps_estimate=_f(h.get("epsEstimate")),
            surprise_pct=_f(h.get("surprisePercent")),
        )
        for h in ((result.get("earningsHistory") or {}).get("history") or [])
    ]

    earnings_mod = result.get("earnings") or {}
    fin_chart = earnings_mod.get("financialsChart") or {}
    quarterly_revenue = [
        {"date": q.get("date"), "revenue": _f(q.get("revenue")), "earnings": _f(q.get("earnings"))}
        for q in fin_chart.get("quarterly") or []
    ]
    quarterly_earnings = [
        {
            "date": q.get("date"),
            "actual": _f(q.get("actual")),
            "estimate": _f(q.get("estimate")),
        }
        for q in (earnings_mod.get("earningsChart") or {}).get("quarterly") or []
    ]

    calendar = None
    cal_module = result.get("calendarEvents")
    if cal_module:
        earnings = cal_module.get("earnings") or {}
        calendar = EarningsDates(
            earnings_dates=[
                d for raw in (earnings.get("earningsDate") or []) if (d := to_date(raw))
            ],
            is_estimate=earnings.get("isEarningsDateEstimate"),
            eps_avg=_f(earnings.get("earningsAverage")),
            eps_low=_f(earnings.get("earningsLow")),
            eps_high=_f(earnings.get("earningsHigh")),
            revenue_avg=_f(earnings.get("revenueAverage")),
        )

    return EarningsData(
        symbol=symbol,
        history=history,
        quarterly_revenue=quarterly_revenue,
        quarterly_earnings=quarterly_earnings,
        calendar=calendar,
    )


# ------------------------------------------------------------------- options


def _parse_contracts(raw: list[dict]) -> list[OptionContract]:
    out: list[OptionContract] = []
    for c in raw or []:
        sym = c.get("contractSymbol")
        strike = _f(c.get("strike"))
        if not sym or strike is None:
            continue
        out.append(
            OptionContract(
                contract_symbol=sym,
                strike=strike,
                last_price=_f(c.get("lastPrice")),
                bid=_f(c.get("bid")),
                ask=_f(c.get("ask")),
                change=_f(c.get("change")),
                percent_change=_f(c.get("percentChange")),
                volume=_i(c.get("volume")),
                open_interest=_i(c.get("openInterest")),
                implied_volatility=_f(c.get("impliedVolatility")),
                in_the_money=c.get("inTheMoney"),
                expiration=to_date(c.get("expiration")),
            )
        )
    return out


def parse_options(result: dict) -> OptionChain:
    quote = result.get("quote") or {}
    options = result.get("options") or []
    block = options[0] if options else {}
    return OptionChain(
        symbol=result.get("underlyingSymbol") or quote.get("symbol", ""),
        expirations=[d for raw in result.get("expirationDates") or [] if (d := to_date(raw))],
        expiry=to_date(block.get("expirationDate")),
        underlying_price=_f(quote.get("regularMarketPrice")),
        calls=_parse_contracts(block.get("calls") or []),
        puts=_parse_contracts(block.get("puts") or []),
    )
