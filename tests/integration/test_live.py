"""Live integration tests against Yahoo Finance (marked; run with -m integration)."""

from __future__ import annotations

import pytest

from yahoo_finance_ai.service import YahooService

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]


@pytest.fixture()
async def service():
    async with YahooService() as s:
        yield s


class TestLive:
    async def test_search(self, service: YahooService) -> None:
        result = await service.search("apple", limit=5)
        assert any(q.symbol == "AAPL" for q in result.quotes)

    async def test_price_us(self, service: YahooService) -> None:
        h = await service.price_history("AAPL", range_="1mo")
        assert h.symbol == "AAPL"
        assert len(h.candles) > 10
        assert h.candles[-1].close and h.candles[-1].close > 0

    async def test_price_international(self, service: YahooService) -> None:
        h = await service.price_history("RELIANCE.NS", range_="1mo")
        assert h.currency == "INR"
        assert len(h.candles) > 10

    async def test_intraday(self, service: YahooService) -> None:
        h = await service.price_history("MSFT", range_="1d", interval="5m")
        assert len(h.candles) > 10

    async def test_quote_multi(self, service: YahooService) -> None:
        quotes = await service.quote(["AAPL", "MSFT", "RELIANCE.NS"])
        assert len(quotes) == 3
        assert all(q.price for q in quotes)

    async def test_fundamentals(self, service: YahooService) -> None:
        stmt = await service.fundamentals("AAPL", statement="income", frequency="annual")
        assert stmt.periods
        assert stmt.periods[0].items.get("totalRevenue")

    async def test_technical(self, service: YahooService) -> None:
        analysis = await service.technical("AAPL", range_="1y")
        assert analysis.snapshot.rsi14 is not None
        assert analysis.snapshot.atr14 is not None
        assert analysis.snapshot.signals

    async def test_events(self, service: YahooService) -> None:
        ev = await service.events("AAPL", range_="5y")
        assert ev.dividends

    async def test_news(self, service: YahooService) -> None:
        items = await service.news("AAPL", limit=5)
        assert items

    async def test_options(self, service: YahooService) -> None:
        chain = await service.options("AAPL")
        assert chain.expirations
        assert chain.calls

    async def test_holders_analysts(self, service: YahooService) -> None:
        assert (await service.holders("AAPL")).institutional
        ad = await service.analysts("AAPL")
        assert ad.price_target and ad.price_target.mean

    async def test_snapshot(self, service: YahooService) -> None:
        snap = await service.snapshot("MSFT")
        assert snap.quote and snap.quote.price
        assert snap.technical is not None
        # tolerate transient per-part failures, but most parts should be present
        present = sum(
            1
            for part in (snap.quote, snap.profile, snap.key_stats, snap.events, snap.analysts, snap.technical)
            if part is not None
        )
        assert present >= 4

    async def test_bad_symbol(self, service: YahooService) -> None:
        from yahoo_finance_ai.exceptions import NotFoundError

        with pytest.raises(NotFoundError):
            await service.price_history("NOTAREALTICKERXX")
