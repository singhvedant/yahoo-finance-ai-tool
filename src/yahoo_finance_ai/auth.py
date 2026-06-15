"""Cookie + crumb session bootstrap for Yahoo's unofficial API.

Yahoo's ``quoteSummary``/``quote``/``options`` endpoints require a consent
cookie (``A3``, obtained from ``fc.yahoo.com``) plus a "crumb" CSRF token
(``/v1/test/getcrumb``). No username/password is involved — this is pure
session bootstrap, persisted to ``~/.yfinance-ai/session.json`` so the CLI,
MCP server, and library share one session.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .exceptions import AuthenticationError

if TYPE_CHECKING:  # pragma: no cover
    from .client import YahooClient

logger = logging.getLogger("yahoo_finance_ai.auth")

DEFAULT_STATE_DIR = Path("~/.yfinance-ai").expanduser()
COOKIE_URL = "https://fc.yahoo.com"
CRUMB_URL = "https://query1.finance.yahoo.com/v1/test/getcrumb"


class SessionStore:
    """Persist cookies + crumb as JSON at ``state_dir/session.json`` (chmod 600)."""

    def __init__(self, state_dir: Path | None = None) -> None:
        self.state_dir = Path(state_dir) if state_dir else DEFAULT_STATE_DIR
        self.path = self.state_dir / "session.json"

    def load(self) -> dict | None:
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict) or "cookies" not in data:
            return None
        return data

    def save(self, cookies: dict[str, str], crumb: str) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "cookies": cookies,
            "crumb": crumb,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
        self.path.write_text(json.dumps(payload, indent=2))
        os.chmod(self.path, 0o600)
        logger.info("Saved Yahoo session state to %s", self.path)

    def clear(self) -> None:
        try:
            self.path.unlink()
            logger.info("Cleared Yahoo session state at %s", self.path)
        except FileNotFoundError:
            pass


def has_session(store: SessionStore) -> bool:
    """True if a persisted session (cookies + crumb) exists on disk."""
    data = store.load()
    return bool(data and data.get("cookies") and data.get("crumb"))


def _looks_invalid(crumb: str) -> bool:
    if not crumb or len(crumb) > 64:
        return True
    lowered = crumb.lower()
    return "too many requests" in lowered or "<html" in lowered or "unauthorized" in lowered


async def bootstrap_session(client: YahooClient) -> str:
    """Fetch consent cookie + crumb, persist them, and return the crumb.

    Raises :class:`AuthenticationError` if Yahoo refuses to issue a crumb.
    """
    session = client.session
    try:
        # fc.yahoo.com returns 404 but sets the A3 cookie on the .yahoo.com domain.
        await session.get(COOKIE_URL, timeout=client.timeout)
    except Exception as exc:  # noqa: BLE001 - transport errors are non-fatal here
        logger.debug("Cookie bootstrap request failed (continuing): %s", exc)

    try:
        resp = await session.get(CRUMB_URL, timeout=client.timeout)
    except Exception as exc:  # noqa: BLE001
        raise AuthenticationError(f"Crumb request failed: {exc}") from exc

    crumb = (resp.text or "").strip()
    if resp.status_code != 200 or _looks_invalid(crumb):
        raise AuthenticationError(
            f"Yahoo refused to issue a crumb (HTTP {resp.status_code}). "
            "Try again shortly; Yahoo throttles aggressively."
        )

    jar = getattr(session.cookies, "jar", None)
    if jar is not None:
        cookies = {c.name: c.value for c in jar if c.value is not None}
    else:
        cookies = dict(session.cookies)
    client.store.save(cookies, crumb)
    client.crumb = crumb
    logger.info("Bootstrapped Yahoo session (crumb acquired)")
    return crumb
