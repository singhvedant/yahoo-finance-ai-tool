"""Parser tests against live-probed fixtures (offline)."""

from __future__ import annotations

import datetime as dt

from yahoo_finance_ai import parsers


class TestUnwrap:
    def test_raw_dict(self) -> None:
        assert parsers.unwrap({"raw": 42, "fmt": "42"}) == 42

    def test_empty_dict_is_none(self) -> None:
        assert parsers.unwrap({}) is None

    def test_passthrough(self) -> None:
        assert parsers.unwrap(3.14) == 3.14
        assert parsers.unwrap("buy") == "buy"
        assert parsers.unwrap(None) is None

    def test_non_raw_dict_passthrough(self) -> None:
        assert parsers.unwrap({"a": 1}) == {"a": 1}


class TestToDate:
    def test_epoch(self) -> None:
        assert parsers.to_date(1628256600) == dt.date(2021, 8, 6)

    def test_iso(self) -> None:
        assert parsers.to_date("2022-09-30") == dt.date(2022, 9, 30)

    def test_wrapped(self) -> None:
        assert parsers.to_date({"raw": 1628256600, "fmt": "2021-08-06"}) == dt.date(2021, 8, 6)

    def test_garbage(self) -> None:
        assert parsers.to_date(None) is None
        assert parsers.to_date("not-a-date") is None


class TestParseChart:
    def test_daily(self, chart_aapl: dict) -> None:
        h = parsers.parse_chart(chart_aapl)
        assert h.symbol == "AAPL"
        assert h.currency == "USD"
        assert h.interval == "1d"
        assert len(h.candles) > 15
        last = h.candles[-1]
        assert last.close and last.close > 0
        assert last.high is not None and last.low is not None
        assert last.high >= last.low
        assert last.volume and last.volume > 0
        assert len(h.closes()) == len(h.dates())

    def test_intraday(self, chart_aapl_intraday: dict) -> None:
        h = parsers.parse_chart(chart_aapl_intraday)
        assert h.symbol == "AAPL"
        assert len(h.candles) > 30
        # intraday timestamps minutes apart
        delta = h.candles[1].ts - h.candles[0].ts
        assert delta <= dt.timedelta(minutes=10)

    def test_international(self, chart_reliance: dict) -> None:
        h = parsers.parse_chart(chart_reliance)
        assert h.symbol == "RELIANCE.NS"
        assert h.currency == "INR"
        assert len(h.candles) > 30


class TestParseEvents:
    def test_dividends(self, chart_aapl_5y: dict) -> None:
        ev = parsers.parse_events(chart_aapl_5y)
        assert ev.symbol == "AAPL"
        assert len(ev.dividends) >= 15
        amounts = {d.amount for d in ev.dividends}
        assert 0.22 in amounts  # known AAPL dividend from fixture
        # sorted chronologically
        dates = [d.date for d in ev.dividends]
        assert dates == sorted(dates)

    def test_calendar_merge(self, chart_aapl_5y: dict, quotesummary_aapl: dict) -> None:
        ev = parsers.parse_events(
            chart_aapl_5y,
            calendar=quotesummary_aapl.get("calendarEvents"),
            summary_detail=quotesummary_aapl.get("summaryDetail"),
        )
        assert ev.calendar is not None
        assert ev.calendar.earnings_dates
        assert ev.ex_dividend_date is not None


class TestParseSearch:
    def test_quotes(self, search_reliance: dict) -> None:
        result = parsers.parse_search(search_reliance, "reliance")
        assert result.query == "reliance"
        symbols = [q.symbol for q in result.quotes]
        assert "RELIANCE.NS" in symbols
        ns = next(q for q in result.quotes if q.symbol == "RELIANCE.NS")
        assert ns.exchange == "NSI"

    def test_news(self, search_apple_news: dict) -> None:
        items = parsers.parse_news(search_apple_news)
        assert len(items) >= 5
        assert all(n.title for n in items)
        assert any(n.published is not None for n in items)
        assert any("AAPL" in (n.related_tickers or []) for n in items)


class TestParseQuote:
    def test_aapl(self, quote_v7: list[dict]) -> None:
        q = parsers.parse_quote(next(x for x in quote_v7 if x["symbol"] == "AAPL"))
        assert q.symbol == "AAPL"
        assert q.price and q.price > 0
        assert q.currency == "USD"
        assert q.market_cap and q.market_cap > 1e12

    def test_international(self, quote_v7: list[dict]) -> None:
        q = parsers.parse_quote(next(x for x in quote_v7 if x["symbol"] == "RELIANCE.NS"))
        assert q.currency == "INR"
        assert q.price and q.price > 0


class TestParseStatement:
    def test_income_annual(self, quotesummary_aapl: dict) -> None:
        stmt = parsers.parse_statement(
            quotesummary_aapl["incomeStatementHistory"], "AAPL", "income", "annual"
        )
        assert stmt.kind == "income"
        assert stmt.frequency == "annual"
        assert len(stmt.periods) == 4
        latest = stmt.periods[0]
        assert latest.end_date is not None
        assert latest.items["totalRevenue"] and latest.items["totalRevenue"] > 1e11

    def test_balance_quarterly(self, quotesummary_aapl: dict) -> None:
        # NOTE: Yahoo deprecated detailed line items in the quarterly statement
        # quoteSummary modules — entries now carry only endDate. The parser must
        # still produce dated periods without crashing.
        stmt = parsers.parse_statement(
            quotesummary_aapl["balanceSheetHistoryQuarterly"], "AAPL", "balance", "quarterly"
        )
        assert stmt.frequency == "quarterly"
        assert len(stmt.periods) == 4
        assert all(p.end_date is not None for p in stmt.periods)


class TestParseKeyStats:
    def test_merged(self, quotesummary_aapl: dict) -> None:
        ks = parsers.parse_key_stats(quotesummary_aapl, "AAPL")
        assert ks.symbol == "AAPL"
        assert len(ks.stats) > 50
        assert isinstance(ks.stats.get("trailingPE"), float)
        assert ks.stats.get("recommendationKey") == "buy"
        assert "maxAge" not in ks.stats


class TestParseProfile:
    def test_profile(self, quotesummary_aapl: dict) -> None:
        p = parsers.parse_profile(
            quotesummary_aapl["summaryProfile"], "AAPL", price=quotesummary_aapl.get("price")
        )
        assert p.sector == "Technology"
        assert p.employees and p.employees > 100_000
        assert p.name and "Apple" in p.name


class TestParseAnalysts:
    def test_analysts(self, quotesummary_aapl: dict) -> None:
        ad = parsers.parse_analysts(quotesummary_aapl, "AAPL")
        assert ad.price_target is not None
        assert ad.price_target.mean and ad.price_target.mean > 0
        assert ad.price_target.analysts and ad.price_target.analysts > 10
        assert ad.trend
        assert ad.trend[0].buy + ad.trend[0].strong_buy > 0
        assert len(ad.upgrades) <= 20
        assert ad.upgrades and ad.upgrades[0]["firm"]


class TestParseHolders:
    def test_holders(self, quotesummary_aapl: dict) -> None:
        hd = parsers.parse_holders(quotesummary_aapl, "AAPL")
        assert hd.breakdown is not None
        assert hd.breakdown.institutions_pct and hd.breakdown.institutions_pct > 0.3
        assert len(hd.institutional) == 10
        assert all(h.organization for h in hd.institutional)
        assert hd.funds


class TestParseEarnings:
    def test_earnings(self, quotesummary_aapl: dict) -> None:
        ed = parsers.parse_earnings(quotesummary_aapl, "AAPL")
        assert len(ed.history) == 4
        assert all(h.eps_actual is not None for h in ed.history)
        assert ed.calendar is not None
        assert ed.calendar.earnings_dates
        assert ed.quarterly_revenue


class TestParseOptions:
    def test_chain(self, options_aapl: dict) -> None:
        chain = parsers.parse_options(options_aapl)
        assert chain.symbol == "AAPL"
        assert len(chain.expirations) > 10
        assert chain.expiry is not None
        assert chain.underlying_price and chain.underlying_price > 0
        assert chain.calls and chain.puts
        call = chain.calls[0]
        assert call.contract_symbol.startswith("AAPL")
        assert call.strike > 0
