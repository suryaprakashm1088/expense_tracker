"""
routes/expenses.py — Core expense CRUD routes and the dashboard.

Routes registered:
  GET         /
  GET/POST    /add
  GET         /expenses
  GET/POST    /edit/<id>
  POST        /delete/<id>
  GET         /receipts
  GET         /sw.js        — Service Worker (must be at root scope for PWA)
"""
import json
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session

import database as db
from extensions import app, login_required
from config import MONTH_NAMES
try:
    from app_metrics import EXPENSE_ADDED, EXPENSE_AMOUNT, DUPLICATE_DETECTED
    _METRICS = True
except Exception:
    _METRICS = False


def _validate_expense_form(title, amount_str, category, date_str, note, shop, label):
    """Validate expense form fields. Returns (amount_float, errors_list)."""
    errors = []
    allowed_categories = db.get_all_categories()

    if not title:
        errors.append("Title is required.")
    elif len(title) > 200:
        errors.append("Title must be 200 characters or fewer.")

    amount_val = None
    try:
        amount_val = float(amount_str)
        if amount_val <= 0:
            errors.append("Amount must be greater than 0.")
        elif amount_val > 1_000_000:
            errors.append("Amount seems too large (max S$1,000,000).")
    except (ValueError, TypeError):
        errors.append("Amount must be a valid number.")

    if category not in allowed_categories:
        errors.append("Invalid category selected.")

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        errors.append("Date must be a valid date (YYYY-MM-DD).")

    if note and len(note) > 500:
        errors.append("Note must be 500 characters or fewer.")
    if shop and len(shop) > 100:
        errors.append("Shop name must be 100 characters or fewer.")
    if label and len(label) > 100:
        errors.append("Label must be 100 characters or fewer.")

    return amount_val, errors


@login_required
@app.route("/")
def index():
    now          = datetime.now()
    stats        = db.get_dashboard_stats()
    monthly_data = db.get_monthly_summary(now.month, now.year)
    pie_labels   = [r["category"] for r in monthly_data]
    pie_values   = [r["total"]    for r in monthly_data]
    monthly_totals = db.get_monthly_totals(now.year)
    bar_labels   = [MONTH_NAMES[int(r["month"])] for r in monthly_totals]
    bar_values   = [r["total"] for r in monthly_totals]
    recent       = db.get_all_expenses(month=now.month, year=now.year)[:5]

    return render_template(
        "index.html",
        stats=stats,
        pie_labels=json.dumps(pie_labels),
        pie_values=json.dumps(pie_values),
        bar_labels=json.dumps(bar_labels),
        bar_values=json.dumps(bar_values),
        recent=recent,
        current_month=MONTH_NAMES[now.month],
        current_year=now.year,
    )


@login_required
@app.route("/add", methods=["GET", "POST"])
def add():
    if request.method == "POST":
        title     = request.form.get("title", "").strip()
        amount    = request.form.get("amount", "0").strip()
        category  = request.form.get("category", "Other")
        date      = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))
        note      = request.form.get("note", "").strip()
        shop      = request.form.get("shop_name", "").strip() or None
        label     = request.form.get("label", "").strip() or None
        confirmed = request.form.get("dup_confirmed", "") == "yes"

        amount_val, errors = _validate_expense_form(title, amount, category, date, note, shop, label)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template(
                "add.html",
                categories=db.get_all_categories(),
                today=datetime.now().strftime("%Y-%m-%d"),
                form=request.form,
            )

        # Group duplicate check
        if not confirmed:
            family_id = None
            if session.get("member_logged_in"):
                member_obj = db.get_member_by_id(session.get("member_id"))
                if member_obj:
                    family_id = member_obj.get("family_id")

            added_by_name = session.get("member_name") or session.get("admin_username") or "Web"
            dup = db.check_group_duplicate(
                amount=amount_val,
                date_str=date,
                family_id=family_id,
                shop_name=shop,
                title=title,
                excluded_added_by=added_by_name,
            )
            if dup:
                if _METRICS:
                    DUPLICATE_DETECTED.labels(source="web").inc()
                return render_template(
                    "add.html",
                    categories=db.get_all_categories(),
                    today=datetime.now().strftime("%Y-%m-%d"),
                    form=request.form,
                    dup_warning={
                        "added_by": dup["added_by"],
                        "amount":   dup["amount"],
                        "title":    dup.get("title") or dup.get("shop_name", ""),
                        "category": dup["category"],
                        "date":     dup["date"],
                    },
                )

        db.add_expense(title, amount_val, category, date, note,
                       added_by="Web", shop_name=shop, label=label)
        if _METRICS:
            EXPENSE_ADDED.labels(method="web", category=category).inc()
            EXPENSE_AMOUNT.labels(category=category).inc(amount_val)
        flash(f"✅ Expense '{title}' of S${amount_val:,.2f} added successfully!", "success")
        return redirect(url_for("index"))

    return render_template(
        "add.html",
        categories=db.get_all_categories(),
        today=datetime.now().strftime("%Y-%m-%d"),
        form={},
    )


@login_required
@app.route("/expenses")
def expenses():
    now      = datetime.now()
    month    = request.args.get("month", now.month)
    year     = request.args.get("year",  now.year)
    category = request.args.get("category", "All")

    rows             = db.get_all_expenses(month=month, year=year, category=category)
    total            = sum(r["amount"] for r in rows)
    available_months = db.get_available_months()

    return render_template(
        "expenses.html",
        expenses=rows,
        total=total,
        categories=["All"] + db.get_all_categories(),
        selected_month=int(month),
        selected_year=int(year),
        selected_category=category,
        month_names=MONTH_NAMES,
        available_months=available_months,
        current_year=now.year,
    )


@login_required
@app.route("/edit/<int:expense_id>", methods=["GET", "POST"])
def edit(expense_id):
    expense = db.get_expense_by_id(expense_id)
    if not expense:
        flash("Expense not found.", "danger")
        return redirect(url_for("expenses"))

    if request.method == "POST":
        title    = request.form.get("title", "").strip()
        amount   = request.form.get("amount", "0").strip()
        category = request.form.get("category", "Other")
        date     = request.form.get("date", "")
        note     = request.form.get("note", "").strip()
        shop     = request.form.get("shop_name", "").strip() or None
        label    = request.form.get("label", "").strip() or None

        amount_val, errors = _validate_expense_form(title, amount, category, date, note, shop, label)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("edit.html", expense=expense, categories=db.get_all_categories())

        db.update_expense(expense_id, title, amount_val, category, date, note,
                          shop_name=shop, label=label)
        flash("✅ Expense updated successfully!", "success")
        return redirect(url_for("expenses"))

    return render_template("edit.html", expense=expense, categories=db.get_all_categories())


@login_required
@app.route("/delete/<int:expense_id>", methods=["POST"])
def delete(expense_id):
    db.delete_expense(expense_id)
    flash("🗑️ Expense deleted.", "info")
    return redirect(url_for("expenses"))


@login_required
@app.route("/receipts")
def receipts():
    receipts_list = db.get_receipts_summary()
    return render_template("receipts.html", receipts=receipts_list)


# ── PWA Service Worker ────────────────────────────────────────────────────────
# Must be served from /sw.js (not /static/sw.js) so it gets scope over the
# entire app. No login required — listed in PUBLIC_ENDPOINTS in config.py.
@app.route("/sw.js")
def service_worker():
    from flask import send_from_directory
    import os
    resp = send_from_directory(
        os.path.join(app.root_path, "static"), "sw.js"
    )
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Content-Type"]  = "application/javascript"
    return resp
