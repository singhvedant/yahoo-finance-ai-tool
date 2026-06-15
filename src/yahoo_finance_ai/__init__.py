"""yahoo_finance_ai — async Yahoo Finance client, CLI, and MCP server."""

from __future__ import annotations

__version__ = "0.1.0"

from .client import YahooClient
from .service import YahooService

__all__ = ["YahooClient", "YahooService", "__version__"]
