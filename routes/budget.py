"""
routes/budget.py — Budget planner: monthly income + fixed expenses + savings projection.

Routes registered:
  GET/POST  /budget
  POST      /budget/income/delete/<id>
  POST      /budget/fixed/delete/<id>
"""
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session

import database as db
from extensions import app, login_required
from config import MONTH_NAMES


@login_required
@app.route("/budget", methods=["GET", "POST"])
def budget():
    now = datetime.now()

    # Resolve family_id from session member
    family_id = None
    if session.get("member_logged_in"):
        member_obj = db.get_member_by_id(session.get("member_id"))
        if member_obj:
            family_id = member_obj.get("family_id")

    if request.method == "POST":
        action = request.form.get("action", "")

        if action == "add_income":
            desc   = request.form.get("description", "").strip()
            amount = request.form.get("amount", "0").strip()
            try:
                amt = float(amount)
                if not desc:
                    flash("Description is required.", "danger")
                elif amt <= 0:
                    flash("Amount must be greater than 0.", "danger")
                else:
                    db.add_income(desc, amt, family_id=family_id)
                    flash(f"✅ Income '{desc}' of S${amt:,.2f} added!", "success")
            except ValueError:
                flash("Invalid amount.", "danger")

        elif action == "add_fixed":
            desc     = request.form.get("description", "").strip()
            amount   = request.form.get("amount", "0").strip()
            category = request.form.get("category", "Fixed").strip()
            try:
                amt = float(amount)
                if not desc:
                    flash("Description is required.", "danger")
                elif amt <= 0:
                    flash("Amount must be greater than 0.", "danger")
                else:
                    db.add_fixed_expense(desc, amt, category=category, family_id=family_id)
                    flash(f"✅ Fixed expense '{desc}' of S${amt:,.2f} added!", "success")
            except ValueError:
                flash("Invalid amount.", "danger")

        return redirect(url_for("budget"))

    month = int(request.args.get("month", now.month))
    year  = int(request.args.get("year",  now.year))

    income_entries = db.get_all_income(family_id=family_id)
    fixed_entries  = db.get_all_fixed_expenses(family_id=family_id)
    budget_summary = db.get_budget_summary(month, year, family_id=family_id)
    available      = db.get_available_months()

    # Group fixed expenses by category for display
    fixed_by_cat = {}
    for fe in fixed_entries:
        cat = fe["category"]
        fixed_by_cat.setdefault(cat, []).append(fe)

    return render_template(
        "budget.html",
        income_entries=income_entries,
        fixed_entries=fixed_entries,
        fixed_by_cat=fixed_by_cat,
        budget_summary=budget_summary,
        selected_month=month,
        selected_year=year,
        month_name=MONTH_NAMES[month],
        available=available,
        month_names=MONTH_NAMES,
        now=now,
    )


@login_required
@app.route("/budget/income/delete/<int:income_id>", methods=["POST"])
def delete_income(income_id):
    db.delete_income(income_id)
    flash("Income entry removed.", "info")
    return redirect(url_for("budget"))


@login_required
@app.route("/budget/fixed/delete/<int:fe_id>", methods=["POST"])
def delete_fixed_expense(fe_id):
    db.delete_fixed_expense(fe_id)
    flash("Fixed expense removed.", "info")
    return redirect(url_for("budget"))
