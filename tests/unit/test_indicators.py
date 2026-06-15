"""Indicator math tests (offline, hand-checked values)."""

from __future__ import annotations

import json
from pathlib import Path

from yahoo_finance_ai import indicators, parsers
from yahoo_finance_ai.models import PriceHistory

FIXTURES = Path(__file__).parent.parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class TestSMA:
    def test_basic(self) -> None:
        out = indicators.sma([1, 2, 3, 4, 5], 3)
        assert out == [None, None, 2.0, 3.0, 4.0]

    def test_too_short(self) -> None:
        assert indicators.sma([1, 2], 5) == [None, None]

    def test_length_preserved(self) -> None:
        assert len(indicators.sma(list(range(100)), 20)) == 100


class TestEMA:
    def test_seed_is_sma(self) -> None:
        out = indicators.ema([1, 2, 3, 4, 5], 3)
        assert out[2] == 2.0  # seeded with SMA(3)
        # next: (4-2)*0.5 + 2 = 3.0 ; then (5-3)*0.5+3 = 4.0
        assert out[3] == 3.0
        assert out[4] == 4.0


class TestRSI:
    def test_all_gains_is_100(self) -> None:
        out = indicators.rsi(list(range(1, 31)), 14)
        assert out[-1] == 100.0

    def test_padding(self) -> None:
        out = indicators.rsi(list(range(1, 31)), 14)
        assert out[:14] == [None] * 14
        assert out[14] is not None

    def test_range(self) -> None:
        vals = [100 + ((-1) ** i) * (i % 7) for i in range(60)]
        out = indicators.rsi([float(v) for v in vals], 14)
        for v in out:
            if v is not None:
                assert 0.0 <= v <= 100.0


class TestMACD:
    def test_alignment_and_sign(self) -> None:
        values = [float(i) for i in range(1, 61)]
        m, s, h = indicators.macd(values)
        assert len(m) == len(s) == len(h) == 60
        # rising series: MACD positive at the end
        assert m[-1] is not None and m[-1] > 0
        assert h[-1] is not None


class TestBollinger:
    def test_band_order(self) -> None:
        values = [float(100 + (i % 5)) for i in range(40)]
        upper, middle, lower = indicators.bollinger(values)
        assert upper[-1] is not None and middle[-1] is not None and lower[-1] is not None
        assert upper[-1] >= middle[-1] >= lower[-1]

    def test_constant_series_zero_width(self) -> None:
        values = [50.0] * 25
        upper, middle, lower = indicators.bollinger(values)
        assert upper[-1] == middle[-1] == lower[-1] == 50.0


class TestATR:
    def test_constant_range(self) -> None:
        n = 30
        highs = [102.0] * n
        lows = [98.0] * n
        closes = [100.0] * n
        out = indicators.atr(highs, lows, closes, 14)
        assert out[:14] == [None] * 14
        # TR is constant 4.0 -> ATR == 4.0
        assert out[-1] is not None and abs(out[-1] - 4.0) < 1e-9

    def test_gap_counts_in_tr(self) -> None:
        highs = [10.0, 20.0, 20.0] + [20.0] * 20
        lows = [9.0, 19.0, 19.0] + [19.0] * 20
        closes = [9.5, 19.5, 19.5] + [19.5] * 20
        out = indicators.atr(highs, lows, closes, 2)
        # first TR includes the 9.5 -> 20 gap
        assert out[2] is not None and out[2] > 1.0


class TestStochastic:
    def test_at_high_is_100(self) -> None:
        n = 20
        closes = [float(i) for i in range(1, n + 1)]
        highs = [c + 0.0 for c in closes]
        lows = [c - 1.0 for c in closes]
        k, d = indicators.stochastic(highs, lows, closes, period=5, smooth_k=1, smooth_d=1)
        assert k[-1] is not None and k[-1] > 90.0
        assert len(k) == len(d) == n

    def test_flat_is_50(self) -> None:
        n = 20
        k, _ = indicators.stochastic([5.0] * n, [5.0] * n, [5.0] * n, period=5, smooth_k=1)
        assert k[-1] == 50.0


class TestSnapshot:
    def _history(self) -> PriceHistory:
        return parsers.parse_chart(load_fixture("chart_aapl_1mo_1d.json"))

    def test_snapshot_fields(self) -> None:
        snap = indicators.compute_snapshot(self._history())
        assert snap.symbol == "AAPL"
        assert snap.close > 0
        assert set(snap.sma) == {20, 50, 100, 200}
        assert snap.sma[20] is not None  # ~22 candles in fixture
        assert snap.sma[200] is None  # not enough data
        assert "rsi" in snap.signals
        assert "stochastic" in snap.signals
        assert snap.stochastic["k"] is not None

    def test_analysis_series(self) -> None:
        analysis = indicators.compute_analysis(self._history(), include_series=True)
        assert analysis.series is not None
        assert "atr14" in analysis.series
        assert "stochastic_k" in analysis.series
        n = len(analysis.series["sma20"].dates)
        for s in analysis.series.values():
            assert len(s.values) == n

    def test_empty_history(self) -> None:
        empty = PriceHistory(symbol="X", interval="1d", range="1mo", candles=[])
        snap = indicators.compute_snapshot(empty)
        assert snap.close == 0.0
        assert snap.signals == {}
