"""
services/investment_fetcher.py — Daily price refresh orchestrator.

refresh_all_holdings(triggered_by="scheduler")
    Iterates every active holding that has a non-manual provider,
    fetches the latest price, writes a snapshot, and logs the run.

refresh_single_holding(holding_id)
    Refresh one holding by ID. Returns {"ok": bool, "price": float, "error": str}.
"""

import logging
from datetime import datetime

import database as db
from services.investment_providers import get_provider, MFAPIProvider, EODHDProvider

log = logging.getLogger(__name__)


def refresh_single_holding(holding_id: int) -> dict:
    """
    Fetch the latest price for one holding and store a snapshot.
    Returns {"ok": True, "price": float, "currency": str, "date": str}
         or {"ok": False, "error": str}.
    """
    holding = db.get_holding(holding_id)
    if not holding:
        return {"ok": False, "error": f"Holding {holding_id} not found"}

    provider_name = holding.get("provider", "manual")
    ticker        = holding.get("ticker", "")

    if provider_name == "manual" or not ticker:
        return {"ok": False, "error": "Manual holding — no automatic price fetch"}

    try:
        provider = get_provider(provider_name)
        result   = provider.fetch_price(ticker)
        price_date = _extract_date(result.get("date"))
        db.upsert_price_snapshot(
            holding_id = holding_id,
            price_date = price_date,
            price      = result["price"],
            currency   = result.get("currency", holding.get("currency", "SGD")),
            source     = result.get("source", provider_name),
        )
        log.info("Refreshed %s (%s) → %s %s on %s",
                 holding["name"], ticker, result["price"], result.get("currency"), price_date)
        return {"ok": True, "price": result["price"],
                "currency": result.get("currency"), "date": price_date}
    except Exception as exc:
        log.warning("Failed to refresh holding %s (%s): %s", holding["name"], ticker, exc)
        return {"ok": False, "error": str(exc)}


def refresh_all_holdings(triggered_by: str = "scheduler") -> dict:
    """
    Refresh prices for every active, non-manual holding.
    Creates a refresh run log entry and returns summary stats.
    """
    run_id  = db.start_refresh_run(triggered_by=triggered_by)
    holdings = [h for h in db.get_holdings(active_only=True)
                if h.get("provider") not in ("manual", "") and h.get("ticker")]

    total   = len(holdings)
    updated = 0
    failed  = 0
    errors  = []

    for h in holdings:
        result = refresh_single_holding(h["id"])
        if result["ok"]:
            updated += 1
        else:
            failed += 1
            errors.append(f"{h['name']}: {result['error']}")

    error_log = "\n".join(errors) if errors else None
    db.finish_refresh_run(run_id, total=total, updated=updated,
                          failed=failed, error_log=error_log)

    log.info("Investment refresh complete: %d/%d updated, %d failed", updated, total, failed)
    return {"total": total, "updated": updated, "failed": failed,
            "run_id": run_id, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _extract_date(raw) -> str:
    """
    Convert whatever the provider returns as a 'date' to YYYY-MM-DD.
    Handles Unix timestamps, ISO strings, and DD-MM-YYYY (MFAPI format).
    Falls back to today.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if not raw:
        return today
    try:
        # Unix timestamp (EODHD returns seconds since epoch)
        ts = int(raw)
        return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        # DD-MMM-YYYY like "01-Jan-2025" or "01-01-2025" (MFAPI)
        for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(str(raw), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass
    return today
