---
name: yahoo-finance-ai-tool
description: Fetch and analyze global stock data from Yahoo Finance — US (AAPL, MSFT) and international tickers (RELIANCE.NS, RELIANCE.BO, 7203.T), quotes, OHLCV history, fundamentals, technicals, options chains, news, holders, analyst targets. Use when the user asks about stock prices, US/global equities, Yahoo Finance data, option chains, or cross-market comparisons. Trigger: /yfinance
---

# yahoo-finance-ai-tool

## When to use

Use this skill whenever the user asks about a listed company on ANY exchange:
price/OHLCV history (daily or intraday), realtime quotes, fundamentals
(income/balance/cashflow, key ratios), technical indicators
(SMA/EMA/RSI/MACD/Bollinger/ATR/Stochastic + signals), dividends/splits/
earnings calendar, news, option chains, institutional holders, or analyst
recommendations/price targets. Symbols use Yahoo suffixes: `AAPL` (US),
`RELIANCE.NS` (NSE), `RELIANCE.BO` (BSE), `7203.T` (Tokyo), `BMW.DE` (Xetra).
For Indian-stock deep dives (shareholding patterns, screener.in ratios, peer
medians) the `screener-ai-tool` skill is complementary; this one adds real
OHLC, options, analyst targets, and global coverage.

## How to use

Prefer the MCP tools if the `yfinance` MCP server is connected; otherwise use
the CLI via Bash.

### Path 1 — MCP tools (`yfin_*`)

| Tool | Args | Notes |
| --- | --- | --- |
| `yfin_search` | `query, limit=10, news=5` | Resolve company name -> symbol (all exchanges) |
| `yfin_quote` | `symbols: list` | Realtime price/change/mcap/P-E for many symbols |
| `yfin_price` | `symbol, range="1y", interval="1d", limit=0` | OHLCV; ranges 1d..max, intraday 1m..1h |
| `yfin_fundamentals` | `symbol, statement="income", frequency="annual"` | income/balance/cashflow |
| `yfin_key_stats` | `symbol` | Valuation ratios, margins, growth |
| `yfin_profile` | `symbol` | Sector, industry, business summary |
| `yfin_technical` | `symbol, range="1y", include_series=False` | Indicators + signals dict |
| `yfin_events` | `symbol, range="5y"` | Dividends, splits, earnings calendar |
| `yfin_earnings` | `symbol` | EPS actual vs estimate history |
| `yfin_news` | `symbol, limit=10` | Recent headlines with links |
| `yfin_options` | `symbol, expiry=""` | Option chain; expiry "YYYY-MM-DD" |
| `yfin_holders` | `symbol` | Insider/institutional breakdown + top holders |
| `yfin_analysts` | `symbol` | Price targets, consensus, rating changes |
| `yfin_snapshot` | `symbol` | Everything in one call (large) |
| `yfin_bulk` | `symbols, dataset="price", range="1y", concurrency=8` | Per-symbol error isolation |
| `yfin_export` | `symbol, what="snapshot", fmt="json", out_path=""` | json/csv/parquet to disk |
| `yfin_login` | — | Refresh cookie+crumb session (no credentials) |
| `yfin_auth_status` | — | Session state |

### Path 2 — CLI via Bash

```bash
uv run --directory ~/Development/yahoo-finance-ai-tool yfin <command> [args...] --json
```

Pass `--json` when parsing programmatically; omit for rich tables. Commands
mirror MCP tools 1:1: `search`, `quote`, `price`, `fundamentals`, `stats`,
`profile`, `technical`, `events`, `earnings`, `news`, `options`, `holders`,
`analysts`, `snapshot`, `bulk`, `export`, plus `login`/`logout`/`auth-status`
and `serve`.

## Worked examples

### 1. Full analysis of a stock

```
yfin_quote(symbols=["AAPL"])
yfin_key_stats(symbol="AAPL")
yfin_fundamentals(symbol="AAPL", statement="income", frequency="annual")
yfin_technical(symbol="AAPL", range="1y")
yfin_analysts(symbol="AAPL")
yfin_news(symbol="AAPL", limit=5)
```

Synthesize: valuation (P/E vs growth), revenue/margin trend, technical
posture (RSI, MACD signal, price vs SMA200, ATR for volatility), analyst
consensus vs current price, and recent news catalysts.

### 2. US vs India cross-check

```
yfin_bulk(symbols=["AAPL","MSFT","RELIANCE.NS","TCS.NS"], dataset="quote")
```

### 3. Options positioning

```
yfin_options(symbol="AAPL")                      # nearest expiry, all strikes
yfin_options(symbol="AAPL", expiry="2026-12-18") # specific expiry
```

Look at put/call open interest around the money and implied volatility.

## Auth / self-healing

Yahoo needs a cookie+crumb session for fundamentals/quotes/options — it is
bootstrapped automatically (NO credentials involved). If tools return
`AuthenticationError`/`RateLimitError`-type errors:

1. Call `yfin_login()` (MCP) or run `yfin login` (CLI) — refreshes the session.
2. Session persists at `~/.yfinance-ai/session.json` and is reused.
3. For large bulk jobs lower `concurrency` (e.g. 4) — Yahoo throttles IPs.

## Notes

- Missing numeric data is `None`, never `0` — treat as "not available".
- Quarterly statement line items are deprecated by Yahoo (only `endDate`
  remains); use annual statements or `yfin_key_stats` for current ratios.
- Per-symbol failures in `yfin_bulk` come back as `{"error": ...}` entries —
  the batch never aborts.
- Options data is mostly US-only; intraday intervals only for recent ranges.
