"""Model behavior tests (offline)."""

from __future__ import annotations

import datetime as dt

from yahoo_finance_ai.models import (
    Candle,
    FullSnapshot,
    PriceHistory,
    Quote,
    SearchQuote,
    TechnicalSnapshot,
)


def _candle(close: float | None = 10.0) -> Candle:
    return Candle(
        ts=dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc),
        open=9.0,
        high=11.0,
        low=8.5,
        close=close,
        volume=1000,
        adj_close=close,
    )


class TestExtraIgnore:
    def test_unknown_fields_ignored(self) -> None:
        q = SearchQuote(symbol="AAPL", totallyUnknownField=123)  # type: ignore[call-arg]
        assert q.symbol == "AAPL"
        assert not hasattr(q, "totallyUnknownField")


class TestPriceHistory:
    def test_closes_skips_none(self) -> None:
        h = PriceHistory(
            symbol="X",
            interval="1d",
            range="5d",
            candles=[_candle(1.0), _candle(None), _candle(3.0)],
        )
        assert h.closes() == [1.0, 3.0]
        assert len(h.dates()) == 2

    def test_round_trip(self) -> None:
        h = PriceHistory(symbol="X", interval="1d", range="5d", candles=[_candle()])
        dumped = h.model_dump(mode="json")
        restored = PriceHistory.model_validate(dumped)
        assert restored.candles[0].close == 10.0


class TestQuote:
    def test_defaults_none(self) -> None:
        q = Quote(symbol="MSFT")
        assert q.price is None
        assert q.extras == {}

    def test_json_dump(self) -> None:
        q = Quote(symbol="MSFT", price=400.5, market_cap=3e12)
        d = q.model_dump(mode="json")
        assert d["price"] == 400.5


class TestFullSnapshot:
    def test_all_parts_optional(self) -> None:
        snap = FullSnapshot(symbol="AAPL")
        d = snap.model_dump(mode="json")
        assert d["quote"] is None
        assert d["news"] == []

    def test_with_technical(self) -> None:
        ts = TechnicalSnapshot(symbol="AAPL", as_of=dt.date(2026, 6, 11), close=295.0)
        snap = FullSnapshot(symbol="AAPL", technical=ts)
        assert snap.model_dump(mode="json")["technical"]["close"] == 295.0
