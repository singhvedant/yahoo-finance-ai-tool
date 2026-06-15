"""Service facade, bulk isolation, auth store, and export tests (offline)."""

from __future__ import annotations

from pathlib import Path

import pytest

from yahoo_finance_ai.auth import SessionStore, has_session
from yahoo_finance_ai.bulk import bulk_fetch
from yahoo_finance_ai.export import export_data
from yahoo_finance_ai.models import PriceHistory
from yahoo_finance_ai.service import YahooService


@pytest.fixture()
def service(fake_client) -> YahooService:
    return YahooService(client=fake_client)


class TestService:
    async def test_search(self, service: YahooService) -> None:
        result = await service.search("reliance", limit=3, news=2)
        assert len(result.quotes) == 3
        assert len(result.news) <= 2

    async def test_quote(self, service: YahooService) -> None:
        quotes = await service.quote(["AAPL", "RELIANCE.NS"])
        symbols = {q.symbol for q in quotes}
        assert "AAPL" in symbols

    async def test_price_history(self, service: YahooService) -> None:
        h = await service.price_history("AAPL", range_="1mo")
        assert h.symbol == "AAPL"
        assert h.candles

    async def test_fundamentals_validation(self, service: YahooService) -> None:
        with pytest.raises(ValueError):
            await service.fundamentals("AAPL", statement="nonsense")

    async def test_fundamentals(self, service: YahooService) -> None:
        stmt = await service.fundamentals("AAPL", statement="income", frequency="annual")
        assert stmt.periods
        assert stmt.periods[0].items.get("totalRevenue")

    async def test_key_stats_and_profile(self, service: YahooService) -> None:
        ks = await service.key_stats("AAPL")
        assert ks.stats
        p = await service.profile("AAPL")
        assert p.sector == "Technology"

    async def test_technical(self, service: YahooService) -> None:
        analysis = await service.technical("AAPL", range_="1mo")
        assert analysis.snapshot.close > 0
        assert analysis.series is None

    async def test_events(self, service: YahooService) -> None:
        ev = await service.events("AAPL", range_="5y")
        assert ev.dividends

    async def test_news(self, service: YahooService) -> None:
        items = await service.news("AAPL", limit=4)
        assert 0 < len(items) <= 4

    async def test_options(self, service: YahooService) -> None:
        chain = await service.options("AAPL")
        assert chain.calls and chain.puts

    async def test_holders_analysts_earnings(self, service: YahooService) -> None:
        assert (await service.holders("AAPL")).institutional
        assert (await service.analysts("AAPL")).price_target
        assert (await service.earnings("AAPL")).history

    async def test_snapshot_tolerates_part_failures(self, service: YahooService, fake_client) -> None:
        snap = await service.snapshot("AAPL")
        assert snap.quote is not None
        assert snap.technical is not None

    async def test_summary_cache(self, service: YahooService, fake_client) -> None:
        await service.key_stats("AAPL")
        calls_before = len(fake_client.calls)
        await service.key_stats("AAPL")
        assert len(fake_client.calls) == calls_before  # cache hit


class TestBulk:
    async def test_error_isolation(self, service: YahooService) -> None:
        results = await bulk_fetch(
            service, ["AAPL", "NOTAREALTICKERXX", "RELIANCE.NS"], dataset="price"
        )
        assert isinstance(results["AAPL"], PriceHistory)
        assert isinstance(results["NOTAREALTICKERXX"], dict)
        assert "error" in results["NOTAREALTICKERXX"]
        assert isinstance(results["RELIANCE.NS"], PriceHistory)

    async def test_invalid_dataset(self, service: YahooService) -> None:
        with pytest.raises(ValueError):
            await bulk_fetch(service, ["AAPL"], dataset="nope")

    async def test_progress_callback(self, service: YahooService) -> None:
        seen: list[tuple[str, bool]] = []
        await bulk_fetch(
            service,
            ["AAPL", "NOTAREALTICKERXX"],
            dataset="quote",
            on_progress=lambda s, ok: seen.append((s, ok)),
        )
        assert ("NOTAREALTICKERXX", False) in seen


class TestExport:
    async def test_json(self, service: YahooService, tmp_path: Path) -> None:
        h = await service.price_history("AAPL")
        path = export_data(h, tmp_path / "out.json", fmt="json")
        assert path.exists() and path.read_text().startswith("{")

    async def test_csv(self, service: YahooService, tmp_path: Path) -> None:
        h = await service.price_history("AAPL")
        path = export_data(h, tmp_path / "out.csv", fmt="csv")
        text = path.read_text()
        assert "close" in text.splitlines()[0]
        assert len(text.splitlines()) > 10

    async def test_parquet(self, service: YahooService, tmp_path: Path) -> None:
        h = await service.price_history("AAPL")
        path = export_data(h, tmp_path / "out.parquet", fmt="parquet")
        import pandas as pd

        frame = pd.read_parquet(path)
        assert len(frame) == len(h.candles)

    async def test_bulk_export(self, service: YahooService, tmp_path: Path) -> None:
        results = await bulk_fetch(service, ["AAPL", "NOTAREALTICKERXX"], dataset="price")
        path = export_data(results, tmp_path / "bulk.csv", fmt="csv")
        assert path.exists()


class TestAuthStore:
    def test_round_trip(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "state")
        assert store.load() is None
        assert not has_session(store)
        store.save({"A3": "cookie-value"}, "crumb123")
        data = store.load()
        assert data and data["crumb"] == "crumb123"
        assert has_session(store)
        assert oct(store.path.stat().st_mode)[-3:] == "600"
        store.clear()
        assert store.load() is None

    def test_corrupt_file(self, tmp_path: Path) -> None:
        store = SessionStore(tmp_path / "state")
        store.state_dir.mkdir(parents=True)
        store.path.write_text("{not json")
        assert store.load() is None

    def test_auth_status_via_service(self, fake_client) -> None:
        service = YahooService(client=fake_client)
        status = service.auth_status()
        assert status["has_crumb"] is True
        assert "state_dir" in status
