"""Bulk fetching with per-symbol error isolation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .service import YahooService

logger = logging.getLogger("yahoo_finance_ai.bulk")

DATASETS = ("price", "quote", "technical", "fundamentals", "key_stats", "snapshot")


async def bulk_fetch(
    service: YahooService,
    symbols: list[str],
    dataset: str = "price",
    range_: str = "1y",
    interval: str = "1d",
    concurrency: int = 8,
    on_progress: Callable[[str, bool], None] | None = None,
) -> dict[str, Any]:
    """Fetch ``dataset`` for every symbol concurrently.

    Returns ``{symbol: model | {"error": str}}`` — never raises for
    individual symbol failures.
    """
    if dataset not in DATASETS:
        raise ValueError(f"Invalid dataset={dataset!r}; expected one of {DATASETS}")

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def fetch_one(symbol: str) -> tuple[str, Any]:
        async with semaphore:
            try:
                if dataset == "price":
                    value: Any = await service.price_history(
                        symbol, range_=range_, interval=interval
                    )
                elif dataset == "quote":
                    quotes = await service.quote([symbol])
                    value = quotes[0] if quotes else {"error": "no quote returned"}
                elif dataset == "technical":
                    value = await service.technical(symbol, range_=range_)
                elif dataset == "fundamentals":
                    value = await service.fundamentals(symbol)
                elif dataset == "key_stats":
                    value = await service.key_stats(symbol)
                else:  # snapshot
                    value = await service.snapshot(symbol)
                ok = not (isinstance(value, dict) and "error" in value)
            except Exception as exc:  # noqa: BLE001 - isolation is the contract
                logger.warning("bulk: %s failed: %s", symbol, exc)
                value = {"error": str(exc)}
                ok = False
            if on_progress is not None:
                try:
                    on_progress(symbol, ok)
                except Exception:  # noqa: BLE001
                    pass
            return symbol, value

    pairs = await asyncio.gather(*(fetch_one(s) for s in symbols))
    return dict(pairs)
