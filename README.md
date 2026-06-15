# yahoo-finance-ai-tool

Async Yahoo Finance client + **CLI** (`yfin`) + **MCP server** for LLM agents.
Fetches everything Yahoo Finance knows about any ticker on any world exchange:
realtime quotes, OHLCV history (daily + intraday), fundamentals, key stats,
technical indicators, dividends/splits/earnings calendar, news, option chains,
holders, and analyst data.

Symbols use Yahoo conventions: `AAPL`, `MSFT` (US), `RELIANCE.NS` (NSE India),
`RELIANCE.BO` (BSE), `7203.T` (Tokyo), `BMW.DE` (Xetra), etc. International
tickers are first-class — everything below works identically for them.

## Architecture

```
yfin CLI (typer+rich)      MCP server "yfinance" (FastMCP: stdio + streamable-http)
        \                     /
         YahooService (facade: per-instance quoteSummary cache, concurrent snapshot)
            |— parsers.py     raw JSON -> pydantic v2 models (unwrap {"raw":..} values)
            |— indicators.py  pure-python SMA/EMA/RSI/MACD/Bollinger/ATR/Stochastic
            |— bulk.py        semaphore-bounded gather, per-symbol error isolation
            |— export.py      json / csv / parquet (pandas+pyarrow)
         YahooClient (curl_cffi AsyncSession, token-bucket rate limit,
            |                 retry+backoff, 401 -> auto crumb refresh)
         auth.py SessionStore (~/.yfinance-ai/session.json: cookies + crumb)
```

### Why curl_cffi and not httpx

Yahoo blocks non-browser **TLS fingerprints**: plain `curl`/httpx receive
HTTP 429 "Too Many Requests" on every `query{1,2}.finance.yahoo.com` endpoint
regardless of headers (verified live 2026-06-12). `curl_cffi` with
`impersonate="chrome"` presents a genuine Chrome TLS/JA3 fingerprint and gets
200s. The rest of the stack (rate limiting, retries, pooling) is our own code
on top of `curl_cffi.requests.AsyncSession`.

### Cookie + crumb auth (no credentials!)

Many endpoints (`quoteSummary`, `quote`, `options`) require a consent cookie
plus a "crumb" CSRF token:

1. `GET https://fc.yahoo.com` → sets the `A3` cookie (response body is a 404 — ignore it)
2. `GET https://query1.finance.yahoo.com/v1/test/getcrumb` → plain-text crumb
3. The crumb is appended as `&crumb=...` to authed endpoints.

This is bootstrapped **automatically and lazily** — no username/password
exists in this flow. The session persists to `~/.yfinance-ai/session.json`
(chmod 600) and is shared by CLI, MCP, and library. On HTTP 401/403 or an
"Invalid Crumb" body the client refreshes the session once and retries. If an
LLM agent sees auth errors, it can self-heal by calling the `yfin_login` MCP
tool / `yfin login` CLI command.

## Have your agent install it (recommended)

Paste this into your AI coding agent (Claude Code, Cursor, etc.):

> Install and set up yahoo-finance-ai-tool by following the instructions at
> https://raw.githubusercontent.com/singhvedant/yahoo-finance-ai-tool/main/llms.txt

The agent will install the package, register the `yfinance` MCP server, and
start using it — no further input needed.

## Install

```bash
pip install yahoo-finance-ai-tool
```

For local development:

```bash
cd yahoo-finance-ai-tool
uv venv && uv pip install -e ".[dev]"
```

## CLI

Every data command accepts `--json` for raw model JSON. `-v` enables debug logs.

```bash
yfin login                      # bootstrap/refresh cookie+crumb session (optional; auto anyway)
yfin auth-status                # {"has_session": true, "has_crumb": true, ...}
yfin logout

yfin search "reliance industries"            # symbols across all exchanges + news
yfin quote AAPL MSFT RELIANCE.NS             # realtime quotes table
yfin price AAPL --range 5y --interval 1wk    # OHLCV history
yfin price AAPL --range 1d --interval 5m     # intraday
yfin fundamentals AAPL --statement income --frequency annual
yfin fundamentals RELIANCE.NS --statement balance
yfin stats AAPL                              # key stats + valuation ratios
yfin profile AAPL                            # sector/industry/summary
yfin technical AAPL --range 1y               # SMA/EMA/RSI/MACD/BB/ATR/Stoch + signals
yfin technical AAPL --series --json          # full date-aligned series
yfin events AAPL --range 10y                 # dividends, splits, earnings calendar
yfin earnings AAPL                           # EPS actual vs estimate history
yfin news AAPL --limit 10
yfin options AAPL --expiry 2026-12-18        # option chain (near-the-money shown)
yfin holders AAPL                            # institutional/fund holders
yfin analysts AAPL                           # price targets + recommendation trend
yfin snapshot AAPL                           # everything in one JSON
yfin bulk AAPL MSFT RELIANCE.NS TCS.NS --dataset price --range 5y --out prices.parquet
yfin export AAPL --what price --fmt csv --range 5y
yfin serve --transport stdio                 # MCP server (default)
yfin serve --transport http --port 8632      # MCP over streamable HTTP at /mcp
```

## MCP server

Server name `yfinance`. Tools:
`yfin_login`, `yfin_auth_status`, `yfin_search`, `yfin_quote`, `yfin_price`,
`yfin_fundamentals`, `yfin_key_stats`, `yfin_profile`, `yfin_technical`,
`yfin_events`, `yfin_earnings`, `yfin_news`, `yfin_options`, `yfin_holders`,
`yfin_analysts`, `yfin_snapshot`, `yfin_bulk`, `yfin_export`.

Register with Claude Code (stdio):

```bash
claude mcp add yfinance -- uv run --directory /Users/skywalker/Development/yahoo-finance-ai-tool yfin serve
```

HTTP variant:

```bash
yfin serve --transport http --host 127.0.0.1 --port 8632
claude mcp add --transport http yfinance http://127.0.0.1:8632/mcp
```

## Testing

```bash
pytest tests/unit -q                          # offline, fixture-driven (no network)
pytest tests/integration -m integration -q    # live Yahoo (needs network)
pytest tests/load -m load -q -s               # 500+ symbols x 5y, concurrency (slow)
```

Fixtures under `tests/fixtures/` were captured live from Yahoo endpoints on
2026-06-12 (chart daily/intraday/5y-with-dividends for AAPL and RELIANCE.NS,
search, quoteSummary with 21 modules, v7 multi-quote, options chain,
fundamentals timeseries, and a bad-symbol error body).

## Endpoints used

| Data | Endpoint | Crumb? |
|---|---|---|
| OHLCV + dividends/splits | `/v8/finance/chart/{symbol}` | no |
| Symbol search + news | `/v1/finance/search` | no |
| Fundamentals/stats/holders/analysts/earnings | `/v10/finance/quoteSummary/{symbol}?modules=...` | yes |
| Realtime quotes (multi) | `/v7/finance/quote?symbols=...` | yes |
| Option chains | `/v7/finance/options/{symbol}` | yes |

## Limitations

- **Unofficial API** — Yahoo can change shapes or block at any time. The
  client is polite (2 req/s token bucket by default, backoff on 429) but
  heavy use may get an IP throttled.
- **Quarterly statement line items are gone**: Yahoo deprecated detailed line
  items in the quarterly `quoteSummary` statement modules (entries carry only
  `endDate` now). Annual statements still include full line items. The
  detailed quarterly data lives in the separate fundamentals-timeseries
  endpoint (fixture saved under `tests/fixtures/timeseries_aapl.json`; not yet
  wired into the service layer).
- Options are mostly available for US-listed tickers.
- Intraday intervals (`1m`..`1h`) only work for recent ranges (Yahoo limit).
- No real login/paid data — this only uses the free public endpoints.
