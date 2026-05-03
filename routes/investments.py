"""
routes/investments.py — Portfolio valuation module.

Routes registered:
  GET       /investments                    Dashboard: holdings list + valuation summary
  POST      /investments/add               Add a new holding
  POST      /investments/edit/<id>         Update an existing holding
  POST      /investments/delete/<id>       Soft-delete (deactivate) a holding
  POST      /investments/refresh           Manual price refresh (AJAX)
  POST      /investments/refresh/<id>      Refresh single holding price (AJAX)
  GET       /investments/search            Ticker/fund search (AJAX → JSON)
  GET       /investments/history/<id>      Price history JSON for a holding
"""

from datetime import datetime

from flask import (
    render_template, request, redirect, url_for,
    flash, session, jsonify
)

import database as db
from extensions import app, login_required


def _family_id():
    """Return family_id from the current session, or None."""
    if session.get("member_logged_in"):
        member = db.get_member_by_id(session.get("member_id"))
        if member:
            return member.get("family_id")
    return None


# ── Dashboard ─────────────────────────────────────────────────────────────────

@login_required
@app.route("/investments")
def investments():
    fid      = _family_id()
    holdings = db.get_holdings(family_id=fid, active_only=True)
    summary  = db.get_portfolio_summary(family_id=fid)
    last_run = db.get_last_refresh_run()
    portfolios = db.get_all_portfolios(family_id=fid)

    # Group holdings by portfolio name for the UI
    portfolio_map = {p["id"]: p["name"] for p in portfolios}
    for h in holdings:
        h["portfolio_name"] = portfolio_map.get(h.get("portfolio_id"), "—")

    # Breakdown by asset type
    stocks = [h for h in holdings if h.get("asset_type") == "stock"]
    mfs    = [h for h in holdings if h.get("asset_type") == "mf"]
    manual = [h for h in holdings if h.get("asset_type") == "manual"]

    from config import EODHD_API_KEY
    eodhd_configured = bool(EODHD_API_KEY)

    return render_template(
        "investments.html",
        holdings       = holdings,
        summary        = summary,
        last_run       = last_run,
        portfolios     = portfolios,
        stocks         = stocks,
        mfs            = mfs,
        manual_holdings= manual,
        eodhd_configured = eodhd_configured,
        now            = datetime.now(),
    )


# ── Add holding ───────────────────────────────────────────────────────────────

@login_required
@app.route("/investments/add", methods=["POST"])
def investment_add():
    fid = _family_id()
    name         = request.form.get("name", "").strip()
    ticker       = request.form.get("ticker", "").strip().upper()
    asset_type   = request.form.get("asset_type", "stock")
    provider     = request.form.get("provider", "manual")
    quantity     = request.form.get("quantity", "0")
    buy_price    = request.form.get("buy_price", "")
    currency     = request.form.get("currency", "SGD")
    notes        = request.form.get("notes", "").strip()
    portfolio_id = request.form.get("portfolio_id") or None

    if not name:
        flash("Holding name is required.", "danger")
        return redirect(url_for("investments"))

    try:
        qty = float(quantity) if quantity else 0
    except ValueError:
        qty = 0
    try:
        bp = float(buy_price) if buy_price else None
    except ValueError:
        bp = None

    hid = db.add_holding(
        name=name, ticker=ticker, asset_type=asset_type,
        provider=provider, quantity=qty, buy_price=bp,
        currency=currency, notes=notes or None,
        portfolio_id=int(portfolio_id) if portfolio_id else None,
        family_id=fid,
    )

    # Immediately try to fetch price if provider is not manual
    if provider != "manual" and ticker:
        try:
            from services.investment_fetcher import refresh_single_holding
            result = refresh_single_holding(hid)
            if result["ok"]:
                flash(f"'{name}' added — current price: {result['currency']} {result['price']:.4f}", "success")
            else:
                flash(f"'{name}' added. Price fetch failed: {result['error']}", "warning")
        except Exception as exc:
            flash(f"'{name}' added. Price fetch error: {exc}", "warning")
    else:
        flash(f"'{name}' added.", "success")

    return redirect(url_for("investments"))


# ── Edit holding ──────────────────────────────────────────────────────────────

@login_required
@app.route("/investments/edit/<int:holding_id>", methods=["POST"])
def investment_edit(holding_id):
    name         = request.form.get("name", "").strip()
    ticker       = request.form.get("ticker", "").strip().upper()
    asset_type   = request.form.get("asset_type", "stock")
    provider     = request.form.get("provider", "manual")
    quantity     = request.form.get("quantity", "0")
    buy_price    = request.form.get("buy_price", "")
    currency     = request.form.get("currency", "SGD")
    notes        = request.form.get("notes", "").strip()
    portfolio_id = request.form.get("portfolio_id") or None

    try:
        qty = float(quantity) if quantity else 0
    except ValueError:
        qty = 0
    try:
        bp = float(buy_price) if buy_price else None
    except ValueError:
        bp = None

    db.update_holding(
        holding_id,
        name=name, ticker=ticker, asset_type=asset_type,
        provider=provider, quantity=qty, buy_price=bp,
        currency=currency, notes=notes or None,
        portfolio_id=int(portfolio_id) if portfolio_id else None,
    )
    flash(f"'{name}' updated.", "success")
    return redirect(url_for("investments"))


# ── Delete (deactivate) holding ───────────────────────────────────────────────

@login_required
@app.route("/investments/delete/<int:holding_id>", methods=["POST"])
def investment_delete(holding_id):
    holding = db.get_holding(holding_id)
    if holding:
        db.delete_holding(holding_id)
        flash(f"'{holding['name']}' deleted.", "success")
    return redirect(url_for("investments"))


# ── Manual refresh all ────────────────────────────────────────────────────────

@login_required
@app.route("/investments/refresh", methods=["POST"])
def investment_refresh_all():
    from services.investment_fetcher import refresh_all_holdings
    result = refresh_all_holdings(triggered_by="manual")
    return jsonify({
        "ok":      True,
        "total":   result["total"],
        "updated": result["updated"],
        "failed":  result["failed"],
        "errors":  result["errors"],
    })


# ── Refresh single holding ────────────────────────────────────────────────────

@login_required
@app.route("/investments/refresh/<int:holding_id>", methods=["POST"])
def investment_refresh_one(holding_id):
    from services.investment_fetcher import refresh_single_holding
    result = refresh_single_holding(holding_id)
    return jsonify(result)


# ── Ticker / fund search ──────────────────────────────────────────────────────

@login_required
@app.route("/investments/search")
def investment_search():
    query         = request.args.get("q", "").strip()
    provider_name = request.args.get("provider", "eodhd")
    if not query:
        return jsonify([])
    try:
        from services.investment_providers import get_provider
        provider = get_provider(provider_name)
        results  = provider.search(query)
        return jsonify(results)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400


# ── Price history for sparklines ─────────────────────────────────────────────

@login_required
@app.route("/investments/history/<int:holding_id>")
def investment_history(holding_id):
    days    = int(request.args.get("days", 30))
    history = db.get_price_history(holding_id, days=days)
    return jsonify(history)
