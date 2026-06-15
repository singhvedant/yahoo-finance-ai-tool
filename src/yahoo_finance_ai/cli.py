"""Typer + rich CLI. Entry point: ``yfin``."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from .exceptions import AuthenticationError, RateLimitError, YahooError
from .service import YahooService

app = typer.Typer(
    name="yfin",
    help="Yahoo Finance data: quotes, OHLCV, fundamentals, technicals, options, news.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging")) -> None:
    _setup_logging(verbose)


def _run(coro: Any) -> Any:
    """Run an async service operation with friendly error handling."""

    async def wrapper() -> Any:
        async with YahooService() as service:
            return await coro(service)

    try:
        return asyncio.run(wrapper())
    except (AuthenticationError, RateLimitError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        err_console.print("Hint: run [bold]yfin login[/bold] to refresh the Yahoo session.")
        raise typer.Exit(1) from exc
    except (YahooError, ValueError) as exc:
        err_console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1) from exc


def _dump(model: Any) -> Any:
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    if isinstance(model, list):
        return [_dump(m) for m in model]
    if isinstance(model, dict):
        return {k: _dump(v) for k, v in model.items()}
    return model


def _print_json(data: Any) -> None:
    console.print_json(json.dumps(_dump(data), default=str))


def _fmt(v: Any, digits: int = 2) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return str(v)


# ------------------------------------------------------------------ auth


@app.command()
def login() -> None:
    """Bootstrap (or refresh) the Yahoo cookie+crumb session. No credentials needed."""
    result = _run(lambda s: s.login())
    if result["ok"]:
        console.print("[green]Session bootstrapped — crumb acquired.[/green]")
    else:
        err_console.print("[red]Session bootstrap failed; try again shortly.[/red]")
        raise typer.Exit(1)


@app.command("refresh-session")
def refresh_session() -> None:
    """Alias for `yfin login`."""
    login()


@app.command("auth-status")
def auth_status() -> None:
    """Show the persisted Yahoo session status."""

    async def op(s: YahooService) -> dict:
        return s.auth_status()

    _print_json(_run(op))


@app.command()
def logout() -> None:
    """Clear the persisted Yahoo session."""

    async def op(s: YahooService) -> dict:
        return s.logout()

    _run(op)
    console.print("Session cleared.")


# ------------------------------------------------------------------ data


@app.command()
def search(
    query: str,
    limit: int = typer.Option(10, help="Max symbol matches"),
    news: int = typer.Option(5, help="Max news items"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Search symbols and news across all Yahoo exchanges."""
    result = _run(lambda s: s.search(query, limit=limit, news=news))
    if json_out:
        _print_json(result)
        return
    table = Table(title=f"Symbols matching {query!r}")
    for col in ("Symbol", "Name", "Exchange", "Type"):
        table.add_column(col)
    for q in result.quotes:
        table.add_row(q.symbol, q.name or "-", q.exch_disp or q.exchange or "-", q.quote_type or "-")
    console.print(table)
    if result.news:
        nt = Table(title="News")
        nt.add_column("Published")
        nt.add_column("Title")
        nt.add_column("Publisher")
        for n in result.news:
            nt.add_row(str(n.published.date()) if n.published else "-", n.title, n.publisher or "-")
        console.print(nt)


@app.command()
def quote(
    symbols: list[str],
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Realtime quote(s) for one or more symbols (AAPL, RELIANCE.NS, ...)."""
    quotes = _run(lambda s: s.quote(symbols))
    if json_out:
        _print_json(quotes)
        return
    table = Table(title="Quotes")
    for col in ("Symbol", "Price", "Chg%", "Mkt Cap", "P/E", "52w High", "52w Low", "State"):
        table.add_column(col, justify="right")
    for q in quotes:
        table.add_row(
            q.symbol,
            _fmt(q.price),
            _fmt(q.change_pct),
            _fmt(q.market_cap, 0),
            _fmt(q.trailing_pe),
            _fmt(q.high_52w),
            _fmt(q.low_52w),
            q.market_state or "-",
        )
    console.print(table)


@app.command()
def price(
    symbol: str,
    range_: str = typer.Option("1y", "--range", help="1d,5d,1mo,3mo,6mo,1y,2y,5y,10y,ytd,max"),
    interval: str = typer.Option("1d", "--interval", help="1m,5m,15m,1h,1d,1wk,1mo"),
    limit: int = typer.Option(30, help="Show latest N rows (0 = all)"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """OHLCV history (daily or intraday)."""
    history = _run(lambda s: s.price_history(symbol, range_=range_, interval=interval))
    if json_out:
        data = _dump(history)
        if limit:
            data["candles"] = data["candles"][-limit:]
        _print_json(data)
        return
    table = Table(title=f"{history.symbol} {range_}/{interval} ({history.currency or '?'})")
    for col in ("Time", "Open", "High", "Low", "Close", "Volume"):
        table.add_column(col, justify="right")
    candles = history.candles[-limit:] if limit else history.candles
    for c in candles:
        table.add_row(
            c.ts.strftime("%Y-%m-%d %H:%M"),
            _fmt(c.open),
            _fmt(c.high),
            _fmt(c.low),
            _fmt(c.close),
            _fmt(c.volume, 0),
        )
    console.print(table)


@app.command()
def fundamentals(
    symbol: str,
    statement: str = typer.Option("income", help="income | balance | cashflow"),
    frequency: str = typer.Option("annual", help="annual | quarterly"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Income statement, balance sheet, or cash flow (annual/quarterly)."""
    stmt = _run(lambda s: s.fundamentals(symbol, statement=statement, frequency=frequency))
    if json_out:
        _print_json(stmt)
        return
    table = Table(title=f"{stmt.symbol} {statement} ({frequency})")
    table.add_column("Line item")
    periods = stmt.periods
    for p in periods:
        table.add_column(str(p.end_date or "?"), justify="right")
    keys: list[str] = []
    for p in periods:
        for k in p.items:
            if k not in keys:
                keys.append(k)
    for k in keys:
        table.add_row(k, *[_fmt(p.items.get(k), 0) for p in periods])
    console.print(table)


@app.command()
def stats(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Key statistics and valuation ratios."""
    ks = _run(lambda s: s.key_stats(symbol))
    if json_out:
        _print_json(ks)
        return
    table = Table(title=f"{ks.symbol} key stats")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in sorted(ks.stats.items()):
        if v is not None:
            table.add_row(k, _fmt(v, 4) if isinstance(v, float) else str(v))
    console.print(table)


@app.command()
def profile(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Company profile: sector, industry, description."""
    p = _run(lambda s: s.profile(symbol))
    if json_out:
        _print_json(p)
        return
    console.print(f"[bold]{p.name or p.symbol}[/bold] ({p.symbol})")
    console.print(f"Sector: {p.sector or '-'} | Industry: {p.industry or '-'}")
    console.print(f"Country: {p.country or '-'} | Employees: {_fmt(p.employees, 0)}")
    console.print(f"Website: {p.website or '-'}")
    if p.summary:
        console.print(f"\n{p.summary}")


@app.command()
def technical(
    symbol: str,
    range_: str = typer.Option("1y", "--range"),
    series: bool = typer.Option(False, "--series", help="Include full indicator series"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Technical indicators: SMA/EMA/RSI/MACD/Bollinger/ATR/Stochastic + signals."""
    analysis = _run(lambda s: s.technical(symbol, range_=range_, include_series=series))
    if json_out:
        _print_json(analysis)
        return
    snap = analysis.snapshot
    console.print(f"[bold]{snap.symbol}[/bold] as of {snap.as_of} close={_fmt(snap.close)}")
    table = Table(title="Indicators")
    table.add_column("Indicator")
    table.add_column("Value", justify="right")
    for p, v in snap.sma.items():
        table.add_row(f"SMA{p}", _fmt(v))
    for p, v in snap.ema.items():
        table.add_row(f"EMA{p}", _fmt(v))
    table.add_row("RSI14", _fmt(snap.rsi14))
    for k, v in snap.macd.items():
        table.add_row(f"MACD {k}", _fmt(v, 4))
    for k, v in snap.bollinger.items():
        table.add_row(f"BB {k}", _fmt(v))
    table.add_row("ATR14", _fmt(snap.atr14))
    for k, v in snap.stochastic.items():
        table.add_row(f"Stoch %{k.upper()}", _fmt(v))
    console.print(table)
    sig = Table(title="Signals")
    sig.add_column("Signal")
    sig.add_column("Reading")
    for k, v in snap.signals.items():
        sig.add_row(k, v)
    console.print(sig)


@app.command()
def events(
    symbol: str,
    range_: str = typer.Option("5y", "--range"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Dividends, splits, and the earnings calendar."""
    ev = _run(lambda s: s.events(symbol, range_=range_))
    if json_out:
        _print_json(ev)
        return
    if ev.dividends:
        table = Table(title=f"{ev.symbol} dividends ({range_})")
        table.add_column("Date")
        table.add_column("Amount", justify="right")
        for d in ev.dividends[-20:]:
            table.add_row(str(d.date), _fmt(d.amount, 4))
        console.print(table)
    if ev.splits:
        table = Table(title="Splits")
        table.add_column("Date")
        table.add_column("Ratio")
        for sp in ev.splits:
            table.add_row(str(sp.date), sp.ratio)
        console.print(table)
    if ev.calendar and ev.calendar.earnings_dates:
        console.print(
            f"Next earnings: {', '.join(str(d) for d in ev.calendar.earnings_dates)}"
            f"{' (estimate)' if ev.calendar.is_estimate else ''}"
        )
    if ev.ex_dividend_date:
        console.print(f"Ex-dividend: {ev.ex_dividend_date} | Pay date: {ev.dividend_date or '-'}")


@app.command()
def earnings(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Earnings history (actual vs estimate) and upcoming dates."""
    ed = _run(lambda s: s.earnings(symbol))
    if json_out:
        _print_json(ed)
        return
    table = Table(title=f"{ed.symbol} earnings history")
    for col in ("Quarter", "EPS actual", "EPS estimate", "Surprise %"):
        table.add_column(col, justify="right")
    for h in ed.history:
        table.add_row(str(h.date or h.period), _fmt(h.eps_actual), _fmt(h.eps_estimate), _fmt(h.surprise_pct, 4))
    console.print(table)
    if ed.calendar and ed.calendar.earnings_dates:
        console.print(f"Next earnings: {', '.join(str(d) for d in ed.calendar.earnings_dates)}")


@app.command()
def news(
    symbol: str,
    limit: int = typer.Option(10),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Recent Yahoo Finance news for a ticker."""
    items = _run(lambda s: s.news(symbol, limit=limit))
    if json_out:
        _print_json(items)
        return
    table = Table(title=f"News: {symbol}")
    table.add_column("Published")
    table.add_column("Title")
    table.add_column("Publisher")
    for n in items:
        table.add_row(str(n.published.date()) if n.published else "-", n.title, n.publisher or "-")
    console.print(table)


@app.command()
def options(
    symbol: str,
    expiry: str = typer.Option("", help="Expiry date YYYY-MM-DD (default: nearest)"),
    limit: int = typer.Option(20, help="Rows per side, nearest the money"),
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Option chain (calls + puts) for an expiry."""
    chain = _run(lambda s: s.options(symbol, expiry=expiry or None))
    if json_out:
        _print_json(chain)
        return
    console.print(
        f"[bold]{chain.symbol}[/bold] expiry {chain.expiry} | underlying {_fmt(chain.underlying_price)} | "
        f"{len(chain.expirations)} expirations available"
    )

    def near_the_money(contracts: list) -> list:
        if chain.underlying_price is None or not limit:
            return contracts[:limit] if limit else contracts
        return sorted(contracts, key=lambda c: abs(c.strike - chain.underlying_price))[:limit]

    for side, contracts in (("Calls", chain.calls), ("Puts", chain.puts)):
        table = Table(title=side)
        for col in ("Strike", "Last", "Bid", "Ask", "Vol", "OI", "IV", "ITM"):
            table.add_column(col, justify="right")
        for c in sorted(near_the_money(contracts), key=lambda c: c.strike):
            table.add_row(
                _fmt(c.strike),
                _fmt(c.last_price),
                _fmt(c.bid),
                _fmt(c.ask),
                _fmt(c.volume, 0),
                _fmt(c.open_interest, 0),
                _fmt(c.implied_volatility, 4),
                "Y" if c.in_the_money else "N",
            )
        console.print(table)


@app.command()
def holders(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Major holders breakdown + top institutional and fund holders."""
    hd = _run(lambda s: s.holders(symbol))
    if json_out:
        _print_json(hd)
        return
    if hd.breakdown:
        b = hd.breakdown
        console.print(
            f"Insiders: {_fmt((b.insiders_pct or 0) * 100)}% | Institutions: "
            f"{_fmt((b.institutions_pct or 0) * 100)}% ({_fmt(b.institutions_count, 0)} institutions)"
        )
    for title, rows in (("Institutional holders", hd.institutional), ("Fund holders", hd.funds)):
        if not rows:
            continue
        table = Table(title=title)
        for col in ("Organization", "% held", "Position", "Value", "Reported"):
            table.add_column(col, justify="right")
        for h in rows[:10]:
            table.add_row(
                h.organization,
                _fmt((h.pct_held or 0) * 100),
                _fmt(h.position, 0),
                _fmt(h.value, 0),
                str(h.report_date or "-"),
            )
        console.print(table)


@app.command()
def analysts(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Analyst recommendations, price targets, and recent rating changes."""
    ad = _run(lambda s: s.analysts(symbol))
    if json_out:
        _print_json(ad)
        return
    if ad.price_target:
        t = ad.price_target
        console.print(
            f"[bold]{ad.symbol}[/bold] target: mean {_fmt(t.mean)} (low {_fmt(t.low)} / high {_fmt(t.high)}) "
            f"from {t.analysts or '?'} analysts — consensus: {t.recommendation_key or '-'}"
        )
    if ad.trend:
        table = Table(title="Recommendation trend")
        for col in ("Period", "Strong buy", "Buy", "Hold", "Sell", "Strong sell"):
            table.add_column(col, justify="right")
        for t in ad.trend:
            table.add_row(t.period, str(t.strong_buy), str(t.buy), str(t.hold), str(t.sell), str(t.strong_sell))
        console.print(table)
    if ad.upgrades:
        table = Table(title="Recent rating changes")
        for col in ("Date", "Firm", "Action", "To"):
            table.add_column(col)
        for u in ad.upgrades[:10]:
            table.add_row(u.get("date", "-"), u.get("firm", "-"), u.get("action", "-"), u.get("to_grade", "-"))
        console.print(table)


@app.command()
def snapshot(
    symbol: str,
    json_out: bool = typer.Option(False, "--json", help="Raw JSON output"),
) -> None:
    """Everything about a symbol in one shot (quote, profile, stats, events, analysts, technicals, news)."""
    snap = _run(lambda s: s.snapshot(symbol))
    _print_json(snap)  # snapshot is inherently large; JSON is the human format too
    _ = json_out


@app.command()
def bulk(
    symbols: list[str],
    dataset: str = typer.Option("price", help="price|quote|technical|fundamentals|key_stats|snapshot"),
    range_: str = typer.Option("1y", "--range"),
    interval: str = typer.Option("1d", "--interval"),
    concurrency: int = typer.Option(8),
    out: str = typer.Option("", help="Write results to file (.json/.csv/.parquet)"),
) -> None:
    """Fetch a dataset for many symbols concurrently (per-symbol error isolation)."""
    from .bulk import bulk_fetch
    from .export import export_data

    def progress(symbol: str, ok: bool) -> None:
        err_console.print(f"  {'[green]ok[/green]' if ok else '[red]fail[/red]'} {symbol}")

    results = _run(
        lambda s: bulk_fetch(
            s,
            symbols,
            dataset=dataset,
            range_=range_,
            interval=interval,
            concurrency=concurrency,
            on_progress=progress,
        )
    )
    succeeded = sum(1 for v in results.values() if not (isinstance(v, dict) and "error" in v))
    console.print(f"Done: {succeeded}/{len(symbols)} succeeded.")
    if out:
        fmt = Path(out).suffix.lstrip(".") or "json"
        path = export_data(results, Path(out), fmt=fmt)  # type: ignore[arg-type]
        console.print(f"Wrote {path}")
    else:
        _print_json(results)


@app.command()
def export(
    symbol: str,
    what: str = typer.Option("snapshot", help="price|fundamentals|snapshot|options"),
    fmt: str = typer.Option("json", help="json|csv|parquet"),
    out: str = typer.Option("", help="Output path (default <symbol>_<what>.<fmt>)"),
    range_: str = typer.Option("1y", "--range"),
) -> None:
    """Export one symbol's data to a file."""
    from .export import export_data

    async def op(s: YahooService) -> Any:
        if what == "price":
            return await s.price_history(symbol, range_=range_)
        if what == "fundamentals":
            return await s.fundamentals(symbol)
        if what == "snapshot":
            return await s.snapshot(symbol)
        if what == "options":
            return await s.options(symbol)
        raise ValueError(f"Invalid what={what!r}; expected price|fundamentals|snapshot|options")

    data = _run(op)
    path = Path(out) if out else Path(f"{symbol}_{what}.{fmt}")
    result_path = export_data(data, path, fmt=fmt)  # type: ignore[arg-type]
    console.print(f"Wrote {result_path}")


@app.command()
def serve(
    transport: str = typer.Option("stdio", help="stdio | http"),
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8632),
) -> None:
    """Run the MCP server (stdio for clients like Claude Code, or streamable HTTP)."""
    from .mcp_server import run_http, run_stdio

    if transport == "http":
        run_http(host=host, port=port)
    elif transport == "stdio":
        run_stdio()
    else:
        err_console.print(f"[red]Invalid transport {transport!r}; use stdio or http.[/red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    sys.exit(app())
