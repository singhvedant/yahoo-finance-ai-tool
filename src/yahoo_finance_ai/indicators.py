"""Pure-python technical indicators (no numpy).

All functions return lists aligned (None-padded) to the input length.
Adapted from screener-ai-tool's indicators with two OHLC-powered additions:
true-range ATR (Wilder) and high/low stochastic %K/%D — Yahoo gives real OHLC.
"""

from __future__ import annotations

import datetime as dt

from .models import (
    IndicatorSeries,
    PriceHistory,
    TechnicalAnalysis,
    TechnicalSnapshot,
)


def sma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average, ``None`` until ``period`` values are available."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    window_sum = sum(values[:period])
    out[period - 1] = window_sum / period
    for i in range(period, n):
        window_sum += values[i] - values[i - period]
        out[i] = window_sum / period
    return out


def ema(values: list[float], period: int) -> list[float | None]:
    """Exponential moving average, seeded with the SMA of the first ``period`` values."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n < period:
        return out
    multiplier = 2.0 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, n):
        prev = (values[i] - prev) * multiplier + prev
        out[i] = prev
    return out


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """Relative Strength Index using Wilder's smoothing."""
    n = len(values)
    out: list[float | None] = [None] * n
    if period <= 0 or n <= period:
        return out

    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        change = values[i] - values[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(avg_gain: float, avg_loss: float) -> float:
        if avg_loss == 0:
            return 100.0
        return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))

    out[period] = _rsi(avg_gain, avg_loss)
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i + 1] = _rsi(avg_gain, avg_loss)
    return out


def macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, signal line, and histogram."""
    n = len(values)
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)

    macd_line: list[float | None] = [None] * n
    for i in range(n):
        f, s = fast_ema[i], slow_ema[i]
        if f is not None and s is not None:
            macd_line[i] = f - s

    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line: list[float | None] = [None] * n
    if first_valid is not None:
        macd_values = [v for v in macd_line[first_valid:] if v is not None]
        for offset, val in enumerate(ema(macd_values, signal)):
            signal_line[first_valid + offset] = val

    histogram: list[float | None] = [None] * n
    for i in range(n):
        m, s = macd_line[i], signal_line[i]
        if m is not None and s is not None:
            histogram[i] = m - s
    return macd_line, signal_line, histogram


def bollinger(
    values: list[float], period: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Bollinger bands: upper, middle (SMA), lower."""
    n = len(values)
    middle = sma(values, period)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(n):
        mid = middle[i]
        if mid is None:
            continue
        window = values[i - period + 1 : i + 1]
        std = (sum((x - mid) ** 2 for x in window) / period) ** 0.5
        upper[i] = mid + num_std * std
        lower[i] = mid - num_std * std
    return upper, middle, lower


def atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> list[float | None]:
    """Average True Range with Wilder smoothing. Inputs must be equal length."""
    n = min(len(highs), len(lows), len(closes))
    out: list[float | None] = [None] * n
    if period <= 0 or n <= period:
        return out

    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)

    prev = sum(trs[:period]) / period
    out[period] = prev
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i + 1] = prev
    return out


def stochastic(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
    smooth_k: int = 3,
    smooth_d: int = 3,
) -> tuple[list[float | None], list[float | None]]:
    """High/low stochastic oscillator: smoothed %K and %D."""
    n = min(len(highs), len(lows), len(closes))
    raw_k: list[float | None] = [None] * n
    for i in range(period - 1, n):
        hh = max(highs[i - period + 1 : i + 1])
        ll = min(lows[i - period + 1 : i + 1])
        raw_k[i] = 50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100.0

    def _smooth(series: list[float | None], window: int) -> list[float | None]:
        if window <= 1:
            return list(series)
        out: list[float | None] = [None] * len(series)
        for i in range(len(series)):
            if i - window + 1 < 0:
                continue
            chunk = series[i - window + 1 : i + 1]
            if any(v is None for v in chunk):
                continue
            out[i] = sum(v for v in chunk if v is not None) / window
        return out

    k = _smooth(raw_k, smooth_k)
    d = _smooth(k, smooth_d)
    return k, d


_SMA_EMA_PERIODS = (20, 50, 100, 200)


def _ohlc_series(
    history: PriceHistory,
) -> tuple[list[dt.date], list[float], list[float], list[float]]:
    """Dates/highs/lows/closes from candles with complete OHLC rows only."""
    dates: list[dt.date] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []
    for c in history.candles:
        if c.close is None or c.high is None or c.low is None:
            continue
        dates.append(c.ts.date())
        highs.append(c.high)
        lows.append(c.low)
        closes.append(c.close)
    return dates, highs, lows, closes


def compute_snapshot(history: PriceHistory) -> TechnicalSnapshot:
    """Latest indicator values + simple qualitative signals."""
    symbol = history.symbol
    dates, highs, lows, closes = _ohlc_series(history)

    if not closes:
        return TechnicalSnapshot(
            symbol=symbol,
            as_of=dt.date.today(),
            close=0.0,
            sma={p: None for p in _SMA_EMA_PERIODS},
            ema={p: None for p in _SMA_EMA_PERIODS},
            rsi14=None,
            macd={"macd": None, "signal": None, "histogram": None},
            bollinger={"upper": None, "middle": None, "lower": None},
            atr14=None,
            stochastic={"k": None, "d": None},
            signals={},
        )

    sma_values = {p: sma(closes, p)[-1] for p in _SMA_EMA_PERIODS}
    ema_values = {p: ema(closes, p)[-1] for p in _SMA_EMA_PERIODS}
    rsi_latest = rsi(closes, 14)[-1]
    macd_line, signal_line, hist_line = macd(closes)
    bb_upper, bb_middle, bb_lower = bollinger(closes)
    atr_latest = atr(highs, lows, closes, 14)[-1]
    stoch_k, stoch_d = stochastic(highs, lows, closes)

    close_latest = closes[-1]
    signals: dict[str, str] = {}

    if rsi_latest is None:
        signals["rsi"] = "unknown"
    elif rsi_latest > 70:
        signals["rsi"] = "overbought"
    elif rsi_latest < 30:
        signals["rsi"] = "oversold"
    else:
        signals["rsi"] = "neutral"

    m_latest, s_latest = macd_line[-1], signal_line[-1]
    if m_latest is None or s_latest is None:
        signals["macd"] = "unknown"
    else:
        prev_m = macd_line[-2] if len(macd_line) >= 2 else None
        prev_s = signal_line[-2] if len(signal_line) >= 2 else None
        if prev_m is not None and prev_s is not None and m_latest > s_latest and prev_m <= prev_s:
            signals["macd"] = "bullish_crossover"
        elif prev_m is not None and prev_s is not None and m_latest < s_latest and prev_m >= prev_s:
            signals["macd"] = "bearish_crossover"
        elif m_latest > s_latest:
            signals["macd"] = "bullish"
        elif m_latest < s_latest:
            signals["macd"] = "bearish"
        else:
            signals["macd"] = "neutral"

    sma200 = sma_values.get(200)
    if sma200 is None:
        signals["trend"] = "unknown"
    elif close_latest > sma200:
        signals["trend"] = "above_sma200"
    else:
        signals["trend"] = "below_sma200"

    if bb_upper[-1] is None or bb_lower[-1] is None:
        signals["bollinger"] = "unknown"
    elif close_latest > bb_upper[-1]:
        signals["bollinger"] = "above_upper"
    elif close_latest < bb_lower[-1]:
        signals["bollinger"] = "below_lower"
    else:
        signals["bollinger"] = "inside"

    k_latest = stoch_k[-1]
    if k_latest is None:
        signals["stochastic"] = "unknown"
    elif k_latest > 80:
        signals["stochastic"] = "overbought"
    elif k_latest < 20:
        signals["stochastic"] = "oversold"
    else:
        signals["stochastic"] = "neutral"

    return TechnicalSnapshot(
        symbol=symbol,
        as_of=dates[-1],
        close=close_latest,
        sma=sma_values,
        ema=ema_values,
        rsi14=rsi_latest,
        macd={"macd": m_latest, "signal": s_latest, "histogram": hist_line[-1]},
        bollinger={"upper": bb_upper[-1], "middle": bb_middle[-1], "lower": bb_lower[-1]},
        atr14=atr_latest,
        stochastic={"k": k_latest, "d": stoch_d[-1]},
        signals=signals,
    )


def compute_analysis(history: PriceHistory, include_series: bool = False) -> TechnicalAnalysis:
    """Technical snapshot, optionally with full date-aligned indicator series."""
    snapshot = compute_snapshot(history)

    series: dict[str, IndicatorSeries] | None = None
    if include_series:
        dates, highs, lows, closes = _ohlc_series(history)
        series = {}
        for period in _SMA_EMA_PERIODS:
            series[f"sma{period}"] = IndicatorSeries(
                name="sma", params={"period": period}, dates=dates, values=sma(closes, period)
            )
            series[f"ema{period}"] = IndicatorSeries(
                name="ema", params={"period": period}, dates=dates, values=ema(closes, period)
            )
        series["rsi14"] = IndicatorSeries(
            name="rsi", params={"period": 14}, dates=dates, values=rsi(closes, 14)
        )
        macd_line, signal_line, hist_line = macd(closes)
        macd_params = {"fast": 12, "slow": 26, "signal": 9}
        series["macd"] = IndicatorSeries(
            name="macd", params=macd_params, dates=dates, values=macd_line
        )
        series["macd_signal"] = IndicatorSeries(
            name="macd_signal", params=macd_params, dates=dates, values=signal_line
        )
        series["macd_histogram"] = IndicatorSeries(
            name="macd_histogram", params=macd_params, dates=dates, values=hist_line
        )
        bb_upper, bb_middle, bb_lower = bollinger(closes)
        bb_params = {"period": 20, "num_std": 2.0}
        series["bb_upper"] = IndicatorSeries(
            name="bb_upper", params=bb_params, dates=dates, values=bb_upper
        )
        series["bb_middle"] = IndicatorSeries(
            name="bb_middle", params=bb_params, dates=dates, values=bb_middle
        )
        series["bb_lower"] = IndicatorSeries(
            name="bb_lower", params=bb_params, dates=dates, values=bb_lower
        )
        series["atr14"] = IndicatorSeries(
            name="atr", params={"period": 14}, dates=dates, values=atr(highs, lows, closes, 14)
        )
        stoch_k, stoch_d = stochastic(highs, lows, closes)
        stoch_params = {"period": 14, "smooth_k": 3, "smooth_d": 3}
        series["stochastic_k"] = IndicatorSeries(
            name="stochastic_k", params=stoch_params, dates=dates, values=stoch_k
        )
        series["stochastic_d"] = IndicatorSeries(
            name="stochastic_d", params=stoch_params, dates=dates, values=stoch_d
        )

    return TechnicalAnalysis(
        symbol=history.symbol, range=history.range, snapshot=snapshot, series=series
    )


__all__ = [
    "sma",
    "ema",
    "rsi",
    "macd",
    "bollinger",
    "atr",
    "stochastic",
    "compute_snapshot",
    "compute_analysis",
]
