# yahoo-finance-ai-tool — Architecture Spec (binding contract for all agents)

Python 3.11+, `uv`-managed. Package: `yahoo_finance_ai` under `src/`. All public APIs below are a
BINDING CONTRACT — implement exact names/signatures so independently-built modules integrate.

```
yahoo-finance-ai-tool/
├── pyproject.toml            # already written — do not modify deps without need
├── SPEC.md                   # this file
├── README.md                 # QA agent
├── src/yahoo_finance_ai/
│   ├── __init__.py           # core agent: exports YahooClient, YahooService, __version__="0.1.0"
│   ├── exceptions.py         # core agent
│   ├── models.py             # core agent
│   ├── auth.py               # core agent
│   ├── client.py             # core agent
│   ├── parsers.py            # data agent
│   ├── indicators.py         # data agent
│   ├── service.py            # data agent
│   ├── bulk.py               # data agent
│   ├── export.py             # data agent
│   ├── cli.py                # interface agent
│   ├── mcp_server.py         # interface agent
│   └── __main__.py           # interface agent: `python -m yahoo_finance_ai` -> cli
├── tests/
│   ├── fixtures/*.json       # already saved (live-probed 2026-06-12) — see list below
│   ├── conftest.py           # QA agent
│   ├── unit/                 # QA agent (parsers, indicators, models, auth, client w/ mocked transport)
│   ├── integration/          # QA agent (live, marked @pytest.mark.integration)
│   └── load/                 # QA agent (marked @pytest.mark.load, pytest-timeout)
└── skills/yahoo-finance-ai-tool/SKILL.md   # QA agent
```

## CRITICAL: transport is curl_cffi, NOT httpx

Yahoo blocks non-browser TLS fingerprints: plain curl/httpx get HTTP 429 "Too Many Requests" on
ALL query{1,2}.finance.yahoo.com endpoints regardless of headers. **Verified live 2026-06-12**:
`curl_cffi` with `impersonate="chrome"` returns 200 everywhere. Therefore `client.py` MUST use
`curl_cffi.requests.AsyncSession(impersonate="chrome")` as the HTTP transport. Everything else
(rate limiter, retry/backoff, pooling) is our own wrapper code. Do not import httpx anywhere.

## Yahoo endpoints (ALL verified live 2026-06-12; fixtures in tests/fixtures/)

Hosts: `https://query1.finance.yahoo.com` (Q1), `https://query2.finance.yahoo.com` (Q2) — interchangeable.

| What | URL | Auth | Fixture |
|---|---|---|---|
| Cookie bootstrap | `GET https://fc.yahoo.com` → 404 body, sets `A3` cookie | — | — |
| Crumb | `GET Q1/v1/test/getcrumb` → plain-text crumb (e.g. `kwx9xrAWW/o`) | cookie | — |
| Chart/OHLCV | `GET Q1/v8/finance/chart/{symbol}?range={r}&interval={i}&events=div%2Csplits` | none | chart_aapl_1mo_1d.json, chart_aapl_1d_5m.json, chart_reliance_ns_3mo_1d.json, chart_aapl_5y_div.json |
| Search+news | `GET Q1/v1/finance/search?q={q}&quotesCount=N&newsCount=N` | none | search_reliance.json, search_apple_news.json |
| Quote summary | `GET Q2/v10/finance/quoteSummary/{symbol}?modules={csv}&crumb={crumb}` | cookie+crumb | quotesummary_aapl.json (21 modules), quotesummary_reliance.json |
| Quote (realtime, multi) | `GET Q1/v7/finance/quote?symbols={csv}&crumb={crumb}` | cookie+crumb | quote_v7_multi.json |
| Options | `GET Q1/v7/finance/options/{symbol}?crumb={crumb}` (+`&date={expiry_epoch}`) | cookie+crumb | options_aapl.json |
| Fundamentals timeseries | `GET Q2/ws/fundamentals-timeseries/v1/finance/timeseries/{symbol}?type={csv}&period1={epoch}&period2={epoch}&crumb={crumb}` | cookie+crumb | timeseries_aapl.json |

Key response shapes (see fixtures for full detail):
- **chart**: `{"chart":{"result":[{"meta":{...currency,symbol,exchangeName,timezone,regularMarketPrice,fiftyTwoWeekHigh/Low,validRanges...}, "timestamp":[epoch...], "events":{"dividends":{"<ts>":{"amount":0.22,"date":ts}}, "splits":{"<ts>":{"numerator":4,"denominator":1,"splitRatio":"4:1","date":ts}}}, "indicators":{"quote":[{"open":[...],"high":[...],"low":[...],"close":[...],"volume":[...]}], "adjclose":[{"adjclose":[...]}]}}], "error":null}}`. Arrays may contain `null` entries (halted bars) — handle. Bad symbol → HTTP 404, body `{"chart":{"result":null,"error":{"code":"Not Found","description":"No data found, symbol may be delisted"}}}`.
- valid ranges: `1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max`; intervals: `1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo` (intraday intervals limited to recent ranges by Yahoo).
- **search**: `{"quotes":[{"symbol","shortname","longname","exchange","exchDisp","quoteType","score","index","typeDisp"...}], "news":[{"uuid","title","publisher","link","providerPublishTime":epoch,"type","relatedTickers":[...]}], ...}` (extra keys ignored).
- **quoteSummary**: `{"quoteSummary":{"result":[{module: {...}}],"error":null}}`. Numeric values are wrapped: `{"raw": 416161000000, "fmt": "416.16B", "longFmt": "..."}` — sometimes value is plain (str/int) or `{}` (empty = missing). Modules verified working: `summaryProfile, summaryDetail, price, defaultKeyStatistics, financialData, incomeStatementHistory, incomeStatementHistoryQuarterly, balanceSheetHistory, balanceSheetHistoryQuarterly, cashflowStatementHistory, cashflowStatementHistoryQuarterly, earnings, earningsHistory, earningsTrend, calendarEvents, recommendationTrend, upgradeDowngradeHistory, majorHoldersBreakdown, institutionOwnership, fundOwnership, insiderHolders`. Statement lists live at e.g. `result[0]["incomeStatementHistory"]["incomeStatementHistory"]` (list of period dicts each with `endDate` + line items). Invalid crumb → HTTP 401 with `"Invalid Crumb"` in body, or 403.
- **options**: `{"optionChain":{"result":[{"underlyingSymbol","expirationDates":[epochs],"strikes":[...],"quote":{...},"options":[{"expirationDate":ts,"calls":[{contractSymbol,strike,lastPrice,change,percentChange,volume,openInterest,bid,ask,contractSize,expiration,lastTradeDate,impliedVolatility,inTheMoney}],"puts":[...]}]}]}}` — plain numbers here, NOT raw/fmt wrapped.
- **v7 quote**: `{"quoteResponse":{"result":[{flat keys: symbol, regularMarketPrice, regularMarketChangePercent, marketCap, trailingPE, epsTrailingTwelveMonths, fiftyTwoWeekHigh/Low, currency, exchange, longName, marketState...}]}}` — plain numbers.
- **timeseries**: `{"timeseries":{"result":[{"meta":{"symbol":["AAPL"],"type":["annualTotalRevenue"]},"timestamp":[...],"annualTotalRevenue":[{"asOfDate":"2022-09-30","periodType":"12M","currencyCode":"USD","reportedValue":{"raw":...,"fmt":...}} , ...]}]}}`.

International symbols use Yahoo suffixes (`.NS` NSE, `.BO` BSE, `.L` LSE...) — same endpoints, verified with RELIANCE.NS.

Politeness: default rate 2 req/s, burst 4. Retry on 429/5xx/transport errors w/ exponential backoff + jitter (max_retries=3). On 401/403 or "Invalid Crumb" → refresh session once automatically, then retry.

## exceptions.py (core agent)

```python
class YahooError(Exception): ...
class AuthenticationError(YahooError): ...      # crumb/cookie refresh failed
class RateLimitError(YahooError):               # attr: retry_after: float | None = None
class NotFoundError(YahooError): ...            # bad/delisted symbol
class ParseError(YahooError): ...
```

## models.py (core agent) — pydantic v2, all models `model_config = ConfigDict(extra="ignore")`

```python
import datetime as dt
from typing import Literal, Any

class SearchQuote(BaseModel): symbol: str; name: str | None; exchange: str | None; exch_disp: str | None; quote_type: str | None; score: float | None
class NewsItem(BaseModel): uuid: str | None; title: str; publisher: str | None; link: str | None; published: dt.datetime | None; related_tickers: list[str] = []
class SearchResult(BaseModel): query: str; quotes: list[SearchQuote]; news: list[NewsItem]

class Quote(BaseModel):  # from v7/finance/quote — flat realtime quote
    symbol: str; name: str | None; currency: str | None; exchange: str | None; market_state: str | None
    price: float | None; change: float | None; change_pct: float | None; previous_close: float | None
    day_high: float | None; day_low: float | None; volume: int | None
    market_cap: float | None; trailing_pe: float | None; forward_pe: float | None; eps_ttm: float | None
    high_52w: float | None; low_52w: float | None; dividend_yield: float | None
    extras: dict[str, Any] = {}   # remaining useful raw fields

class Candle(BaseModel): ts: dt.datetime; open: float | None; high: float | None; low: float | None; close: float | None; volume: int | None; adj_close: float | None
class PriceHistory(BaseModel):
    symbol: str; currency: str | None; timezone: str | None; interval: str; range: str
    candles: list[Candle]
    def closes(self) -> list[float]: ...   # non-None closes, chronological
    def dates(self) -> list[dt.date]: ...  # aligned to closes()

class DividendEvent(BaseModel): date: dt.date; amount: float
class SplitEvent(BaseModel): date: dt.date; numerator: float; denominator: float; ratio: str
class EarningsDates(BaseModel): earnings_dates: list[dt.date] = []; is_estimate: bool | None; eps_avg: float | None; eps_low: float | None; eps_high: float | None; revenue_avg: float | None
class CorporateEvents(BaseModel): symbol: str; dividends: list[DividendEvent]; splits: list[SplitEvent]; calendar: EarningsDates | None; ex_dividend_date: dt.date | None; dividend_date: dt.date | None

class StatementPeriod(BaseModel): end_date: dt.date | None; period_type: str | None; items: dict[str, float | None]  # line item -> raw value
class FinancialStatement(BaseModel): symbol: str; kind: Literal["income","balance","cashflow"]; frequency: Literal["annual","quarterly"]; currency: str | None; periods: list[StatementPeriod]
class KeyStats(BaseModel): symbol: str; stats: dict[str, float | str | bool | None]   # flattened summaryDetail+defaultKeyStatistics+financialData (raw values)
class CompanyProfile(BaseModel): symbol: str; name: str | None; sector: str | None; industry: str | None; website: str | None; country: str | None; employees: int | None; summary: str | None

class RecommendationTrend(BaseModel): period: str; strong_buy: int; buy: int; hold: int; sell: int; strong_sell: int
class PriceTarget(BaseModel): current: float | None; mean: float | None; high: float | None; low: float | None; median: float | None; analysts: int | None; recommendation_key: str | None; recommendation_mean: float | None
class AnalystData(BaseModel): symbol: str; price_target: PriceTarget | None; trend: list[RecommendationTrend]; upgrades: list[dict[str, Any]]   # recent first, cap 20

class MajorHoldersBreakdown(BaseModel): insiders_pct: float | None; institutions_pct: float | None; institutions_float_pct: float | None; institutions_count: int | None
class InstitutionalHolder(BaseModel): organization: str; pct_held: float | None; position: float | None; value: float | None; report_date: dt.date | None
class HoldersData(BaseModel): symbol: str; breakdown: MajorHoldersBreakdown | None; institutional: list[InstitutionalHolder]; funds: list[InstitutionalHolder]

class EarningsPeriod(BaseModel): period: str | None; date: dt.date | None; eps_actual: float | None; eps_estimate: float | None; surprise_pct: float | None
class EarningsData(BaseModel): symbol: str; history: list[EarningsPeriod]; quarterly_revenue: list[dict[str, Any]]; quarterly_earnings: list[dict[str, Any]]; calendar: EarningsDates | None

class OptionContract(BaseModel): contract_symbol: str; strike: float; last_price: float | None; bid: float | None; ask: float | None; change: float | None; percent_change: float | None; volume: int | None; open_interest: int | None; implied_volatility: float | None; in_the_money: bool | None; expiration: dt.date | None
class OptionChain(BaseModel): symbol: str; expirations: list[dt.date]; expiry: dt.date | None; underlying_price: float | None; calls: list[OptionContract]; puts: list[OptionContract]

class IndicatorSeries(BaseModel): name: str; params: dict[str, Any]; dates: list[dt.date]; values: list[float | None]
class TechnicalSnapshot(BaseModel):
    symbol: str; as_of: dt.date; close: float
    sma: dict[int, float | None]; ema: dict[int, float | None]; rsi14: float | None
    macd: dict[str, float | None]; bollinger: dict[str, float | None]
    atr14: float | None; stochastic: dict[str, float | None]   # {"k":..,"d":..}
    signals: dict[str, str]   # e.g. {"rsi":"neutral","macd":"bullish_crossover","trend":"above_sma200","bollinger":"inside","stochastic":"overbought"}
class TechnicalAnalysis(BaseModel): symbol: str; range: str; snapshot: TechnicalSnapshot; series: dict[str, IndicatorSeries] | None

class FullSnapshot(BaseModel): symbol: str; quote: Quote | None; profile: CompanyProfile | None; key_stats: KeyStats | None; events: CorporateEvents | None; analysts: AnalystData | None; technical: TechnicalSnapshot | None; news: list[NewsItem] = []
```

## auth.py (core agent) — cookie+crumb session (no username/password; bootstrap only)

```python
DEFAULT_STATE_DIR = Path("~/.yfinance-ai").expanduser()
class SessionStore:                      # JSON file state_dir/session.json, chmod 600
    def __init__(self, state_dir: Path | None = None): ...
    def load(self) -> dict | None        # {"cookies": {name: value}, "crumb": str, "created_at": iso} or None
    def save(self, cookies: dict[str, str], crumb: str) -> None
    def clear(self) -> None
async def bootstrap_session(client: "YahooClient") -> str
    # GET https://fc.yahoo.com (ignore 404 body; collects A3 cookie into client session),
    # then GET Q1/v1/test/getcrumb -> crumb text. If crumb empty or contains "Too Many Requests"
    # or "<html" -> raise AuthenticationError. Saves cookies+crumb via store. Returns crumb.
def has_session(store: SessionStore) -> bool
```

## client.py (core agent)

```python
class RateLimiter:    # async token bucket
    def __init__(self, rate: float = 2.0, burst: int = 4): ...
    async def acquire(self) -> None

class YahooClient:
    Q1 = "https://query1.finance.yahoo.com"; Q2 = "https://query2.finance.yahoo.com"
    def __init__(self, state_dir: Path | None = None, rate: float = 2.0, burst: int = 4,
                 max_retries: int = 3, timeout: float = 20.0): ...
    # curl_cffi.requests.AsyncSession(impersonate="chrome"); loads cookies+crumb from SessionStore
    # at init; lazy bootstrap: if a crumb-requiring call has no crumb, bootstrap first.
    # Retry w/ exp backoff + jitter on 429/5xx/transport errors; after retries on 429 -> RateLimitError.
    # 404 -> NotFoundError. 401/403 (or body containing "Invalid Crumb") -> refresh session once
    # (re-bootstrap) and retry the request; if still failing -> AuthenticationError.
    async def __aenter__ / __aexit__ / aclose()
    @property def has_crumb(self) -> bool
    async def get_json(self, url: str, params: dict | None = None, need_crumb: bool = False) -> Any
        # central request path: rate-limit, inject crumb param when need_crumb, retries, error mapping
    async def refresh_session(self) -> bool       # delegates to auth.bootstrap_session; True on success
    def logout(self) -> None                      # clear store + session cookies
    # convenience wrappers (thin; return raw parsed JSON dicts):
    async def chart(self, symbol: str, range_: str = "1y", interval: str = "1d", events: str = "div,splits") -> dict
    async def search_raw(self, query: str, quotes_count: int = 10, news_count: int = 10) -> dict
    async def quote_summary(self, symbol: str, modules: list[str]) -> dict      # need_crumb=True; result[0] dict; missing result -> NotFoundError
    async def quotes_raw(self, symbols: list[str]) -> list[dict]                # v7 quote, need_crumb=True
    async def options_raw(self, symbol: str, date: int | None = None) -> dict   # need_crumb=True; result[0]
```

## parsers.py (data agent) — pure functions over raw JSON dicts (see fixtures!)

```python
def unwrap(v: Any) -> Any            # {"raw": x, ...} -> x; {} -> None; passthrough otherwise
def to_date(epoch_or_str) -> dt.date | None    # epoch int, "2022-09-30", or None
def parse_search(payload: dict, query: str) -> SearchResult
def parse_news(payload: dict) -> list[NewsItem]
def parse_quote(item: dict) -> Quote                       # one v7 quote result item
def parse_chart(payload: dict) -> PriceHistory             # full chart JSON -> candles (skip all-None bars NOT — keep, fields None)
def parse_events(payload: dict, calendar: dict | None, summary_detail: dict | None) -> CorporateEvents
    # payload = chart JSON w/ events; calendar = calendarEvents module; summary_detail for ex/dividend dates
def parse_statement(module: dict, symbol: str, kind: str, frequency: str) -> FinancialStatement
    # module = e.g. quoteSummary result[0]["incomeStatementHistory"]; inner list key mirrors module name
def parse_key_stats(result: dict, symbol: str) -> KeyStats # merge summaryDetail+defaultKeyStatistics+financialData, unwrap all
def parse_profile(module: dict, symbol: str) -> CompanyProfile      # summaryProfile (+price for name)
def parse_analysts(result: dict, symbol: str) -> AnalystData        # financialData (targets) + recommendationTrend + upgradeDowngradeHistory
def parse_holders(result: dict, symbol: str) -> HoldersData
def parse_earnings(result: dict, symbol: str) -> EarningsData       # earningsHistory + earnings + calendarEvents
def parse_options(result: dict) -> OptionChain
```

## indicators.py (data agent) — pure python, no numpy; None-padded to input length

ADAPT from `/Users/skywalker/Development/screener-ai-tool/src/screener_ai/indicators.py` (read it).
Same sma/ema/rsi/macd/bollinger functions. CHANGES: add true-range ATR and high/low stochastic
(we have real OHLC here), and snapshot builders take PriceHistory from THIS package's models.

```python
def sma(values: list[float], period: int) -> list[float | None]
def ema(values: list[float], period: int) -> list[float | None]
def rsi(values: list[float], period: int = 14) -> list[float | None]
def macd(values, fast=12, slow=26, signal=9) -> tuple[list, list, list]
def bollinger(values, period=20, num_std=2.0) -> tuple[list, list, list]
def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float | None]   # Wilder
def stochastic(highs, lows, closes, period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> tuple[list, list]  # %K, %D
def compute_snapshot(history: PriceHistory) -> TechnicalSnapshot      # use candles w/ complete OHLC rows only
def compute_analysis(history: PriceHistory, include_series: bool = False) -> TechnicalAnalysis
```

## service.py (data agent) — high-level facade; the ONLY thing CLI/MCP call

```python
DEFAULT_MODULES: dict[str, list[str]]  # per-method module lists
class YahooService:
    def __init__(self, client: YahooClient | None = None): ...
    async def __aenter__/__aexit__/aclose()
    async def login(self) -> dict                  # refresh_session; {"ok": bool, "crumb_present": bool}
    def auth_status(self) -> dict                  # {"has_session": bool, "has_crumb": bool, "state_dir": str}
    def logout(self) -> dict
    async def search(self, query: str, limit: int = 10, news: int = 5) -> SearchResult
    async def quote(self, symbols: list[str]) -> list[Quote]
    async def price_history(self, symbol: str, range_: str = "1y", interval: str = "1d") -> PriceHistory
    async def fundamentals(self, symbol: str, statement: str = "income", frequency: str = "annual") -> FinancialStatement
        # statement ∈ {income,balance,cashflow}; maps to quoteSummary module names
    async def key_stats(self, symbol: str) -> KeyStats
    async def profile(self, symbol: str) -> CompanyProfile
    async def technical(self, symbol: str, range_: str = "1y", include_series: bool = False) -> TechnicalAnalysis
    async def events(self, symbol: str, range_: str = "5y") -> CorporateEvents     # chart events + calendarEvents+summaryDetail
    async def earnings(self, symbol: str) -> EarningsData
    async def news(self, symbol: str, limit: int = 10) -> list[NewsItem]
    async def options(self, symbol: str, expiry: str | None = None) -> OptionChain # expiry "YYYY-MM-DD" -> epoch date param
    async def holders(self, symbol: str) -> HoldersData
    async def analysts(self, symbol: str) -> AnalystData
    async def snapshot(self, symbol: str) -> FullSnapshot                          # gather concurrently, tolerate per-part failures (None)
    # cache quoteSummary result dicts per (symbol, modules-frozenset), maxsize 16, per instance
```

## bulk.py (data agent)

```python
async def bulk_fetch(service: YahooService, symbols: list[str], dataset: str = "price",
                     range_: str = "1y", interval: str = "1d", concurrency: int = 8,
                     on_progress: Callable[[str, bool], None] | None = None) -> dict[str, Any]
# dataset ∈ {"price","quote","technical","fundamentals","key_stats","snapshot"}; semaphore-bounded
# gather; returns {symbol: model | {"error": str}} — never raises for individual failures
```

## export.py (data agent)

```python
def export_data(data: Any, path: Path, fmt: Literal["json","csv","parquet"] = "json") -> Path
# pydantic -> model_dump(mode="json"); PriceHistory/FinancialStatement/OptionChain/bulk dicts get
# tabular CSV/parquet via pandas
```

## cli.py (interface agent) — typer + rich; entry script `yfin`

Global pattern: `--json` flag for raw JSON output on every data command; async wrapped in `asyncio.run`.
Errors → stderr + exit 1; AuthenticationError/RateLimitError → suggest `yfin login`.
Commands (names exact):
- `yfin login` (bootstrap cookie+crumb; prints status), `yfin refresh-session` (alias), `yfin auth-status`, `yfin logout`
- `yfin search QUERY [--limit 10] [--news 5]`
- `yfin quote SYMBOLS...` (rich table)
- `yfin price SYMBOL [--range 1y] [--interval 1d] [--limit 30]` (latest rows)
- `yfin fundamentals SYMBOL [--statement income|balance|cashflow] [--frequency annual|quarterly]`
- `yfin stats SYMBOL` (key stats), `yfin profile SYMBOL`
- `yfin technical SYMBOL [--range 1y] [--series]`
- `yfin events SYMBOL [--range 5y]`, `yfin earnings SYMBOL`
- `yfin news SYMBOL [--limit 10]`
- `yfin options SYMBOL [--expiry YYYY-MM-DD] [--limit 20]` (near-the-money rows)
- `yfin holders SYMBOL`, `yfin analysts SYMBOL`
- `yfin snapshot SYMBOL`
- `yfin bulk SYMBOLS... [--dataset price] [--range 1y] [--concurrency 8] [--out FILE]`
- `yfin export SYMBOL [--what price|fundamentals|snapshot|options] [--fmt json|csv|parquet] [--out FILE] [--range 1y]`
- `yfin serve [--transport stdio|http] [--host 127.0.0.1] [--port 8632]`

## mcp_server.py (interface agent)

`mcp` python SDK `FastMCP` (package `mcp[cli]`). Server name `yfinance`. One shared YahooService
(lazy init). Tools (exact names; return JSON-serializable dicts via model_dump(mode="json")):
`yfin_login()`, `yfin_auth_status()`, `yfin_search(query, limit=10, news=5)`,
`yfin_quote(symbols: list[str])`, `yfin_price(symbol, range="1y", interval="1d", limit=0)`,
`yfin_fundamentals(symbol, statement="income", frequency="annual")`, `yfin_key_stats(symbol)`,
`yfin_profile(symbol)`, `yfin_technical(symbol, range="1y", include_series=False)`,
`yfin_events(symbol, range="5y")`, `yfin_earnings(symbol)`, `yfin_news(symbol, limit=10)`,
`yfin_options(symbol, expiry="")`, `yfin_holders(symbol)`, `yfin_analysts(symbol)`,
`yfin_snapshot(symbol)`, `yfin_bulk(symbols: list[str], dataset="price", range="1y", concurrency=8)`,
`yfin_export(symbol, what="snapshot", fmt="json", out_path="")`.
Docstrings = LLM-facing tool descriptions; note yfin_login exists to self-heal 401/blocked sessions
(no credentials needed). `run(transport="stdio")` default; HTTP via `streamable-http` honoring
host/port (FastMCP settings) — wired to `yfin serve --transport http`.

## Conventions
- `from __future__ import annotations`, full type hints.
- Logging: `logging.getLogger("yahoo_finance_ai...")`; no prints in library code.
- Never log cookies/crumb values.
- Lenient parsing: missing → None, never 0. All quoteSummary values pass through `parsers.unwrap`.
- Tests must not hit network unless marked integration/load. Unit tests mock at
  `YahooClient.get_json` / convenience-wrapper level with fixture JSON (curl_cffi has no respx —
  monkeypatch, do NOT use respx).
- International symbols are first-class: anything with a Yahoo suffix must flow through unchanged.
