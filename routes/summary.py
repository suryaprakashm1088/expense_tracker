"""
routes/summary.py — Monthly summary, API endpoints, and AI/Ollama status.

Routes registered:
  GET   /summary
  GET   /api/category-detail
  GET   /api/monthly-data
  GET   /api/ai-summary
  GET   /api/ai-status
  GET   /api/ollama-status   (alias)
"""
import json
from datetime import datetime

from flask import render_template, request, jsonify, session

import database as db
import local_ai as ollama_cl
from extensions import app, login_required
from config import MONTH_NAMES


@login_required
@app.route("/summary")
def summary():
    now   = datetime.now()
    month = int(request.args.get("month", now.month))
    year  = int(request.args.get("year",  now.year))

    family_id = None
    if session.get("member_logged_in"):
        member_obj = db.get_member_by_id(session.get("member_id"))
        if member_obj:
            family_id = member_obj.get("family_id")

    category_data = db.get_monthly_summary(month, year, family_id=family_id)
    all_expenses  = db.get_all_expenses(month=month, year=year, family_id=family_id)
    grand_total   = sum(r["total"] for r in category_data)

    for row in category_data:
        row["pct"] = round(row["total"] / grand_total * 100, 1) if grand_total else 0

    pie_labels = json.dumps([r["category"] for r in category_data])
    pie_values = json.dumps([r["total"]    for r in category_data])

    # Daily spending line chart
    day_map = {}
    for exp in all_expenses:
        d = exp["date"]
        day_map[d] = day_map.get(d, 0) + exp["amount"]
    sorted_days = sorted(day_map.keys())
    line_labels = json.dumps(sorted_days)
    line_values = json.dumps([round(day_map[d], 2) for d in sorted_days])

    available = db.get_available_months()

    # Top 3 spends per category for the inline drill-down accordion
    top_by_cat = db.get_all_top_by_category(month, year, limit=3, family_id=family_id)

    # Week-level top per category (for "this week" tab inside drill-down)
    week_top_by_cat = {}
    for cat in [r["category"] for r in category_data]:
        wt = db.get_top_expenses_this_week_by_category(cat, limit=3, family_id=family_id)
        if wt:
            week_top_by_cat[cat] = wt

    return render_template(
        "summary.html",
        category_data=category_data,
        grand_total=grand_total,
        selected_month=month,
        selected_year=year,
        month_name=MONTH_NAMES[month],
        pie_labels=pie_labels,
        pie_values=pie_values,
        line_labels=line_labels,
        line_values=line_values,
        available=available,
        month_names=MONTH_NAMES,
        top_by_cat=top_by_cat,
        week_top_by_cat=week_top_by_cat,
    )


@login_required
@app.route("/api/category-detail")
def api_category_detail():
    """Return top spends for a category in the current month and week (JSON)."""
    category  = request.args.get("category", "")
    month     = int(request.args.get("month", datetime.now().month))
    year      = int(request.args.get("year",  datetime.now().year))
    family_id = None
    if session.get("member_logged_in"):
        member_obj = db.get_member_by_id(session.get("member_id"))
        if member_obj:
            family_id = member_obj.get("family_id")
    month_top = db.get_top_expenses_by_category(category, month, year,
                                                 limit=5, family_id=family_id)
    week_top  = db.get_top_expenses_this_week_by_category(category, limit=5,
                                                           family_id=family_id)
    return jsonify({"category": category, "month_top": month_top, "week_top": week_top})


@login_required
@app.route("/api/monthly-data")
def api_monthly_data():
    month = int(request.args.get("month", datetime.now().month))
    year  = int(request.args.get("year",  datetime.now().year))
    data  = db.get_monthly_summary(month, year)
    return jsonify(data)


@login_required
@app.route("/api/ai-summary")
def api_ai_summary():
    """Generate an AI spending summary with Docker Model Runner (AJAX endpoint)."""
    now   = datetime.now()
    month = int(request.args.get("month", now.month))
    year  = int(request.args.get("year",  now.year))

    if not ollama_cl.is_available():
        return jsonify({
            "ok":    False,
            "error": (
                "Docker Model Runner is not available.\n"
                "Make sure Docker Desktop is running and the model is pulled:\n"
                "  docker model pull ai/llama3.2"
            ),
        }), 503

    category_data = db.get_monthly_summary(month, year)
    all_expenses  = db.get_all_expenses(month=month, year=year)
    grand_total   = sum(r["total"] for r in category_data)

    if grand_total == 0:
        return jsonify({
            "ok":      True,
            "summary": f"No expenses recorded for {MONTH_NAMES[month]} {year} yet.",
        })

    for r in category_data:
        r["pct"] = round(r["total"] / grand_total * 100, 1) if grand_total else 0

    try:
        summary_text = ollama_cl.summarise_expenses_with_ollama(
            expenses=all_expenses,
            month_name=MONTH_NAMES[month],
            year=year,
            grand_total=grand_total,
            category_data=category_data,
        )
        return jsonify({"ok": True, "summary": summary_text})
    except Exception as e:
        app.logger.error(f"AI summary API error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@login_required
@app.route("/api/ai-status")
@app.route("/api/ollama-status")   # kept for backwards compatibility
def api_ollama_status():
    """Health-check: is Docker Model Runner reachable, and which models are loaded?"""
    available = ollama_cl.is_available()
    models    = ollama_cl.get_loaded_models() if available else []
    return jsonify({
        "available":       available,
        "models":          models,
        "vision_model":    ollama_cl.VISION_MODEL,
        "text_model":      ollama_cl.TEXT_MODEL,
        "model_runner_url": ollama_cl.MODEL_RUNNER_URL,
    })
