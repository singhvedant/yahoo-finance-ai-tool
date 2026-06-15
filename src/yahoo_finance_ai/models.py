"""Pydantic v2 models for Yahoo Finance data."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


# ---------------------------------------------------------------- search/news


class SearchQuote(_Base):
    symbol: str
    name: str | None = None
    exchange: str | None = None
    exch_disp: str | None = None
    quote_type: str | None = None
    score: float | None = None


class NewsItem(_Base):
    uuid: str | None = None
    title: str
    publisher: str | None = None
    link: str | None = None
    published: dt.datetime | None = None
    related_tickers: list[str] = []


class SearchResult(_Base):
    query: str
    quotes: list[SearchQuote] = []
    news: list[NewsItem] = []


# --------------------------------------------------------------------- quote


class Quote(_Base):
    symbol: str
    name: str | None = None
    currency: str | None = None
    exchange: str | None = None
    market_state: str | None = None
    price: float | None = None
    change: float | None = None
    change_pct: float | None = None
    previous_close: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: int | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    eps_ttm: float | None = None
    high_52w: float | None = None
    low_52w: float | None = None
    dividend_yield: float | None = None
    extras: dict[str, Any] = {}


# --------------------------------------------------------------------- price


class Candle(_Base):
    ts: dt.datetime
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    volume: int | None = None
    adj_close: float | None = None


class PriceHistory(_Base):
    symbol: str
    currency: str | None = None
    timezone: str | None = None
    interval: str
    range: str
    candles: list[Candle] = []

    def closes(self) -> list[float]:
        """Non-None closes, chronological."""
        return [c.close for c in self.candles if c.close is not None]

    def dates(self) -> list[dt.date]:
        """Dates aligned to :meth:`closes`."""
        return [c.ts.date() for c in self.candles if c.close is not None]


# -------------------------------------------------------------------- events


class DividendEvent(_Base):
    date: dt.date
    amount: float


class SplitEvent(_Base):
    date: dt.date
    numerator: float
    denominator: float
    ratio: str


class EarningsDates(_Base):
    earnings_dates: list[dt.date] = []
    is_estimate: bool | None = None
    eps_avg: float | None = None
    eps_low: float | None = None
    eps_high: float | None = None
    revenue_avg: float | None = None


class CorporateEvents(_Base):
    symbol: str
    dividends: list[DividendEvent] = []
    splits: list[SplitEvent] = []
    calendar: EarningsDates | None = None
    ex_dividend_date: dt.date | None = None
    dividend_date: dt.date | None = None


# -------------------------------------------------------------- fundamentals


class StatementPeriod(_Base):
    end_date: dt.date | None = None
    period_type: str | None = None
    items: dict[str, float | None] = {}


class FinancialStatement(_Base):
    symbol: str
    kind: Literal["income", "balance", "cashflow"]
    frequency: Literal["annual", "quarterly"]
    currency: str | None = None
    periods: list[StatementPeriod] = []


class KeyStats(_Base):
    symbol: str
    stats: dict[str, float | str | bool | None] = {}


class CompanyProfile(_Base):
    symbol: str
    name: str | None = None
    sector: str | None = None
    industry: str | None = None
    website: str | None = None
    country: str | None = None
    employees: int | None = None
    summary: str | None = None


# ------------------------------------------------------------------ analysts


class RecommendationTrend(_Base):
    period: str
    strong_buy: int = 0
    buy: int = 0
    hold: int = 0
    sell: int = 0
    strong_sell: int = 0


class PriceTarget(_Base):
    current: float | None = None
    mean: float | None = None
    high: float | None = None
    low: float | None = None
    median: float | None = None
    analysts: int | None = None
    recommendation_key: str | None = None
    recommendation_mean: float | None = None


class AnalystData(_Base):
    symbol: str
    price_target: PriceTarget | None = None
    trend: list[RecommendationTrend] = []
    upgrades: list[dict[str, Any]] = []


# ------------------------------------------------------------------- holders


class MajorHoldersBreakdown(_Base):
    insiders_pct: float | None = None
    institutions_pct: float | None = None
    institutions_float_pct: float | None = None
    institutions_count: int | None = None


class InstitutionalHolder(_Base):
    organization: str
    pct_held: float | None = None
    position: float | None = None
    value: float | None = None
    report_date: dt.date | None = None


class HoldersData(_Base):
    symbol: str
    breakdown: MajorHoldersBreakdown | None = None
    institutional: list[InstitutionalHolder] = []
    funds: list[InstitutionalHolder] = []


# ------------------------------------------------------------------ earnings


class EarningsPeriod(_Base):
    period: str | None = None
    date: dt.date | None = None
    eps_actual: float | None = None
    eps_estimate: float | None = None
    surprise_pct: float | None = None


class EarningsData(_Base):
    symbol: str
    history: list[EarningsPeriod] = []
    quarterly_revenue: list[dict[str, Any]] = []
    quarterly_earnings: list[dict[str, Any]] = []
    calendar: EarningsDates | None = None


# ------------------------------------------------------------------- options


class OptionContract(_Base):
    contract_symbol: str
    strike: float
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    change: float | None = None
    percent_change: float | None = None
    volume: int | None = None
    open_interest: int | None = None
    implied_volatility: float | None = None
    in_the_money: bool | None = None
    expiration: dt.date | None = None


class OptionChain(_Base):
    symbol: str
    expirations: list[dt.date] = []
    expiry: dt.date | None = None
    underlying_price: float | None = None
    calls: list[OptionContract] = []
    puts: list[OptionContract] = []


# ----------------------------------------------------------------- technical


class IndicatorSeries(_Base):
    name: str
    params: dict[str, Any] = {}
    dates: list[dt.date] = []
    values: list[float | None] = []


class TechnicalSnapshot(_Base):
    symbol: str
    as_of: dt.date
    close: float
    sma: dict[int, float | None] = {}
    ema: dict[int, float | None] = {}
    rsi14: float | None = None
    macd: dict[str, float | None] = {}
    bollinger: dict[str, float | None] = {}
    atr14: float | None = None
    stochastic: dict[str, float | None] = {}
    signals: dict[str, str] = {}


class TechnicalAnalysis(_Base):
    symbol: str
    range: str
    snapshot: TechnicalSnapshot
    series: dict[str, IndicatorSeries] | None = None


# ------------------------------------------------------------------ snapshot


class FullSnapshot(_Base):
    symbol: str
    quote: Quote | None = None
    profile: CompanyProfile | None = None
    key_stats: KeyStats | None = None
    events: CorporateEvents | None = None
    analysts: AnalystData | None = None
    technical: TechnicalSnapshot | None = None
    news: list[NewsItem] = []
