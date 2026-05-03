"""
services/investment_providers.py — Price data providers for the investment module.

Provider hierarchy:
  EODHDProvider  — end-of-day prices for global stocks + Indian equities via eodhd.com
  MFAPIProvider  — Indian mutual fund NAV via mfapi.in (free, no key required)

Each provider exposes:
  fetch_price(ticker) → {"price": float, "currency": str, "date": str, "source": str}
  search(query)       → [{"ticker": str, "name": str, "exchange": str, "type": str}, ...]

Providers raise ValueError on unsupported tickers or missing config.
They raise requests.RequestException on network failures.
"""

import os
import logging

import requests

log = logging.getLogger(__name__)

# ── request timeout (seconds) ─────────────────────────────────────────────────
_TIMEOUT = 10


# ─────────────────────────────────────────────────────────────────────────────
# EODHD — global + Indian stocks
# ─────────────────────────────────────────────────────────────────────────────

class EODHDProvider:
    """
    Fetches end-of-day prices from https://eodhd.com

    Ticker format:
      "RELIANCE.NSE"   — NSE-listed Indian stock
      "INFY.BSE"       — BSE-listed Indian stock
      "AAPL.US"        — US stock
      "0700.HK"        — Hong Kong stock
      "D05.SGX"        — SGX Singapore stock

    Free tier: 20 requests/day.  Use the 'demo' key for testing.
    """

    BASE = "https://eodhd.com/api"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.getenv("EODHD_API_KEY", "demo")

    # ── public interface ──────────────────────────────────────────────────────

    def fetch_price(self, ticker: str) -> dict:
        """
        Return latest end-of-day price for ticker.
        Returns dict: {price, currency, date, source}
        """
        ticker = ticker.strip().upper()
        url = f"{self.BASE}/real-time/{ticker}"
        resp = requests.get(url, params={"api_token": self.api_key, "fmt": "json"},
                            timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise ValueError(f"EODHD error for {ticker}: {data['error']}")

        price = float(data.get("close") or data.get("previousClose") or 0)
        if price == 0:
            raise ValueError(f"EODHD returned zero price for {ticker}")

        # Infer currency from exchange suffix
        exchange = ticker.split(".")[-1] if "." in ticker else ""
        currency = _exchange_currency(exchange)

        return {
            "price":    price,
            "currency": currency,
            "date":     data.get("timestamp", ""),
            "source":   "eodhd",
        }

    def search(self, query: str, exchange: str = "") -> list:
        """Search for tickers matching query. Returns list of dicts."""
        params = {
            "api_token":     self.api_key,
            "search_ticker": query,
            "fmt":           "json",
        }
        if exchange:
            params["exchange"] = exchange
        try:
            resp = requests.get(f"{self.BASE}/search/{query}",
                                params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("EODHD search failed: %s", exc)
            return []

        results = []
        for item in (data if isinstance(data, list) else []):
            results.append({
                "ticker":   item.get("Code", "") + "." + item.get("Exchange", ""),
                "name":     item.get("Name", ""),
                "exchange": item.get("Exchange", ""),
                "type":     item.get("Type", "stock"),
                "provider": "eodhd",
            })
        return results[:20]

    def is_configured(self) -> bool:
        return bool(self.api_key) and self.api_key != "demo"


# ─────────────────────────────────────────────────────────────────────────────
# MFAPI — Indian mutual funds
# ─────────────────────────────────────────────────────────────────────────────

class MFAPIProvider:
    """
    Fetches Indian mutual fund NAVs from https://www.mfapi.in (free, no auth).

    Ticker is the numeric scheme code from AMFI, e.g. "100119" (Mirae Asset Large Cap).
    Use search() to find scheme codes by fund name.
    """

    BASE = "https://api.mfapi.in/mf"

    def fetch_price(self, ticker: str) -> dict:
        """Return latest NAV for a mutual fund scheme code."""
        ticker = ticker.strip()
        resp = requests.get(f"{self.BASE}/{ticker}/latest", timeout=_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()

        status = data.get("status", "")
        if status != "SUCCESS":
            raise ValueError(f"MFAPI: scheme {ticker} not found")

        nav_data = data.get("data", [{}])[0]
        price = float(nav_data.get("nav", 0))
        if price == 0:
            raise ValueError(f"MFAPI returned zero NAV for scheme {ticker}")

        return {
            "price":    price,
            "currency": "INR",
            "date":     nav_data.get("date", ""),
            "source":   "mfapi",
        }

    def search(self, query: str, **_) -> list:
        """Search MF schemes by name. Returns list of dicts with scheme code as ticker."""
        try:
            resp = requests.get(f"{self.BASE}/search",
                                params={"q": query}, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.warning("MFAPI search failed: %s", exc)
            return []

        results = []
        for item in (data if isinstance(data, list) else []):
            results.append({
                "ticker":   str(item.get("schemeCode", "")),
                "name":     item.get("schemeName", ""),
                "exchange": "AMFI",
                "type":     "mf",
                "provider": "mfapi",
            })
        return results[:20]

    def is_configured(self) -> bool:
        return True  # no API key required


# ─────────────────────────────────────────────────────────────────────────────
# Provider factory
# ─────────────────────────────────────────────────────────────────────────────

def get_provider(provider_name: str):
    """Return a configured provider instance by name."""
    name = (provider_name or "").lower()
    if name == "eodhd":
        return EODHDProvider()
    if name == "mfapi":
        return MFAPIProvider()
    raise ValueError(f"Unknown provider: {provider_name!r}. Use 'eodhd' or 'mfapi'.")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_EXCHANGE_CURRENCY = {
    "NSE":  "INR",
    "BSE":  "INR",
    "US":   "USD",
    "SGX":  "SGD",
    "HK":   "HKD",
    "LSE":  "GBP",
    "TO":   "CAD",
    "AX":   "AUD",
    "PA":   "EUR",
    "XETRA":"EUR",
    "MI":   "EUR",
    "MC":   "EUR",
    "SW":   "CHF",
    "TSE":  "JPY",
    "KL":   "MYR",
}


def _exchange_currency(exchange: str) -> str:
    return _EXCHANGE_CURRENCY.get(exchange.upper(), "USD")
