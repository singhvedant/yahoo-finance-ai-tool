"""Shared fixtures: fixture-file loaders + an offline mocked YahooClient."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from yahoo_finance_ai.client import YahooClient
from yahoo_finance_ai.exceptions import NotFoundError

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture()
def chart_aapl() -> dict:
    return load_fixture("chart_aapl_1mo_1d.json")


@pytest.fixture()
def chart_aapl_intraday() -> dict:
    return load_fixture("chart_aapl_1d_5m.json")


@pytest.fixture()
def chart_aapl_5y() -> dict:
    return load_fixture("chart_aapl_5y_div.json")


@pytest.fixture()
def chart_reliance() -> dict:
    return load_fixture("chart_reliance_ns_3mo_1d.json")


@pytest.fixture()
def search_reliance() -> dict:
    return load_fixture("search_reliance.json")


@pytest.fixture()
def search_apple_news() -> dict:
    return load_fixture("search_apple_news.json")


@pytest.fixture()
def quotesummary_aapl() -> dict:
    return load_fixture("quotesummary_aapl.json")["quoteSummary"]["result"][0]


@pytest.fixture()
def quote_v7() -> list[dict]:
    return load_fixture("quote_v7_multi.json")["quoteResponse"]["result"]


@pytest.fixture()
def options_aapl() -> dict:
    return load_fixture("options_aapl.json")["optionChain"]["result"][0]


class FakeYahooClient(YahooClient):
    """Offline client: serves fixture payloads, no network, no session file."""

    def __init__(self, tmp_path: Path) -> None:
        super().__init__(state_dir=tmp_path / "state", rate=10_000.0, burst=100)
        self.crumb = "test-crumb"
        self.calls: list[tuple[str, Any]] = []
        self.fail_symbols: set[str] = {"NOTAREALTICKERXX"}

    def _check(self, symbol: str) -> None:
        if symbol.upper() in self.fail_symbols:
            raise NotFoundError(f"No data found for {symbol}")

    async def chart(self, symbol: str, range_: str = "1y", interval: str = "1d",
                    events: str = "div,splits") -> dict:
        self.calls.append(("chart", symbol))
        self._check(symbol)
        if symbol.upper().endswith(".NS"):
            return load_fixture("chart_reliance_ns_3mo_1d.json")
        if interval == "5m":
            return load_fixture("chart_aapl_1d_5m.json")
        if range_ == "5y":
            return load_fixture("chart_aapl_5y_div.json")
        return load_fixture("chart_aapl_1mo_1d.json")

    async def search_raw(self, query: str, quotes_count: int = 10, news_count: int = 10) -> dict:
        self.calls.append(("search", query))
        if "aapl" in query.lower():
            return load_fixture("search_apple_news.json")
        return load_fixture("search_reliance.json")

    async def quote_summary(self, symbol: str, modules: list[str]) -> dict:
        self.calls.append(("quote_summary", (symbol, tuple(sorted(modules)))))
        self._check(symbol)
        return load_fixture("quotesummary_aapl.json")["quoteSummary"]["result"][0]

    async def quotes_raw(self, symbols: list[str]) -> list[dict]:
        self.calls.append(("quotes", tuple(symbols)))
        all_quotes = load_fixture("quote_v7_multi.json")["quoteResponse"]["result"]
        wanted = {s.upper() for s in symbols if s.upper() not in self.fail_symbols}
        return [q for q in all_quotes if q["symbol"].upper() in wanted]

    async def options_raw(self, symbol: str, date: int | None = None) -> dict:
        self.calls.append(("options", symbol))
        self._check(symbol)
        return load_fixture("options_aapl.json")["optionChain"]["result"][0]

    async def get_json(self, url: str, params: dict | None = None,
                       need_crumb: bool = False) -> Any:  # pragma: no cover - guard
        raise AssertionError("FakeYahooClient must not hit the network")

    async def aclose(self) -> None:
        await super().aclose()


@pytest.fixture()
def fake_client(tmp_path: Path) -> FakeYahooClient:
    return FakeYahooClient(tmp_path)
