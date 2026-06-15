"""Export models/bulk results to json, csv, or parquet."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from .models import FinancialStatement, OptionChain, PriceHistory

logger = logging.getLogger("yahoo_finance_ai.export")


def _to_jsonable(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return {k: _to_jsonable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_to_jsonable(v) for v in data]
    return data


def _to_rows(data: Any) -> list[dict] | None:
    """Best-effort tabular conversion for CSV/parquet."""
    if isinstance(data, PriceHistory):
        return [
            {"symbol": data.symbol, **c.model_dump(mode="json")} for c in data.candles
        ]
    if isinstance(data, FinancialStatement):
        rows = []
        for p in data.periods:
            rows.append(
                {
                    "symbol": data.symbol,
                    "kind": data.kind,
                    "frequency": data.frequency,
                    "end_date": str(p.end_date) if p.end_date else None,
                    **p.items,
                }
            )
        return rows
    if isinstance(data, OptionChain):
        rows = []
        for side, contracts in (("call", data.calls), ("put", data.puts)):
            for c in contracts:
                rows.append({"symbol": data.symbol, "side": side, **c.model_dump(mode="json")})
        return rows
    if isinstance(data, dict):  # bulk results: {symbol: model | {"error": ...}}
        rows = []
        for symbol, value in data.items():
            if isinstance(value, PriceHistory):
                rows.extend(_to_rows(value) or [])
            elif isinstance(value, BaseModel):
                dumped = value.model_dump(mode="json")
                flat = {
                    k: v for k, v in dumped.items() if isinstance(v, (int, float, str, bool))
                }
                rows.append({"symbol": symbol, **flat})
            else:
                rows.append({"symbol": symbol, "error": str(value)})
        return rows
    if isinstance(data, list) and all(isinstance(x, BaseModel) for x in data):
        return [x.model_dump(mode="json") for x in data]
    return None


def export_data(
    data: Any, path: Path, fmt: Literal["json", "csv", "parquet"] = "json"
) -> Path:
    """Write ``data`` to ``path`` in the requested format; returns the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        path.write_text(json.dumps(_to_jsonable(data), indent=2, default=str))
        return path

    rows = _to_rows(data)
    if rows is None:
        raise ValueError(
            f"Data of type {type(data).__name__} cannot be exported as {fmt}; use json."
        )

    import pandas as pd

    frame = pd.DataFrame(rows)
    if fmt == "csv":
        frame.to_csv(path, index=False)
    elif fmt == "parquet":
        frame.to_parquet(path, index=False)
    else:
        raise ValueError(f"Invalid fmt={fmt!r}; expected json, csv, or parquet")
    logger.info("Exported %d rows to %s", len(rows), path)
    return path
