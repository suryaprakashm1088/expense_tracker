"""
routes/credit_cards.py — Monthly credit card bill tracking per member per bank.

Routes registered:
  GET/POST  /credit-cards
  POST      /credit-cards/delete/<id>
  GET/POST  /credit-cards/upload
  GET       /credit-cards/review/<upload_id>
  POST      /credit-cards/add-transaction   (AJAX)
"""
import uuid
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, session, jsonify

import database as db
from extensions import app, login_required
from config import MONTH_NAMES, SG_CC_BANKS
try:
    from app_metrics import EXPENSE_ADDED, EXPENSE_AMOUNT, STATEMENT_IMPORT, STATEMENT_TXN_ADDED
    _METRICS = True
except Exception:
    _METRICS = False


@login_required
@app.route("/credit-cards", methods=["GET", "POST"])
def credit_cards():
    now = datetime.now()

    # Resolve family_id from session member
    family_id = None
    if session.get("member_logged_in"):
        member_obj = db.get_member_by_id(session.get("member_id"))
        if member_obj:
            family_id = member_obj.get("family_id")

    if request.method == "POST":
        bank     = request.form.get("bank_name", "").strip().upper()
        amount   = request.form.get("amount", "0").strip()
        member   = request.form.get("member_name", "").strip()
        date_val = request.form.get("date", datetime.now().strftime("%Y-%m-%d"))
        note     = request.form.get("note", "").strip()

        errors     = []
        amount_val = None
        if not bank:
            errors.append("Bank name is required.")
        if not member:
            errors.append("Member name is required.")
        try:
            amount_val = float(amount)
            if amount_val <= 0:
                errors.append("Amount must be greater than 0.")
        except (ValueError, TypeError):
            errors.append("Amount must be a valid number.")

        if errors:
            for e in errors:
                flash(e, "danger")
        else:
            db.add_cc_bill(bank, amount_val, member, date_val,
                           note=note, family_id=family_id)
            flash(f"✅ {bank} CC bill of S${amount_val:,.2f} added for {member}!", "success")

        return redirect(url_for("credit_cards",
                                month=request.args.get("month", now.month),
                                year=request.args.get("year",  now.year)))

    month = int(request.args.get("month", now.month))
    year  = int(request.args.get("year",  now.year))

    bills      = db.get_cc_bills(month=month, year=year, family_id=family_id)
    cc_summary = db.get_cc_summary(month=month, year=year, family_id=family_id)
    members    = db.get_all_members()
    total      = sum(b["amount"] for b in bills)

    # Group by member
    by_member     = {}
    member_totals = {}
    for b in bills:
        by_member.setdefault(b["member_name"], []).append(b)
    for m_name, m_bills in by_member.items():
        member_totals[m_name] = sum(b["amount"] for b in m_bills)

    return render_template(
        "credit_cards.html",
        bills=bills,
        by_member=by_member,
        member_totals=member_totals,
        cc_summary=cc_summary,
        total=total,
        members=members,
        selected_month=month,
        selected_year=year,
        month_name=MONTH_NAMES[month],
        month_names=MONTH_NAMES,
        sg_banks=sorted(set(SG_CC_BANKS.values())),
        today=datetime.now().strftime("%Y-%m-%d"),
        now=now,
    )


@login_required
@app.route("/credit-cards/delete/<int:bill_id>", methods=["POST"])
def delete_cc_bill(bill_id):
    db.delete_cc_bill(bill_id)
    flash("CC bill entry removed.", "info")
    return redirect(url_for("credit_cards"))


# ── Statement upload ──────────────────────────────────────────────────────────

@login_required
@app.route("/credit-cards/upload", methods=["GET", "POST"])
def statement_upload():
    """Upload a bank statement CSV or PDF for processing."""
    family_id = None
    if session.get("member_logged_in"):
        member_obj = db.get_member_by_id(session.get("member_id"))
        if member_obj:
            family_id = member_obj.get("family_id")

    if request.method == "GET":
        return render_template(
            "statement_upload.html",
            sg_banks=sorted(set(SG_CC_BANKS.values())),
        )

    # POST — process uploaded file
    bank_name = request.form.get("bank_name", "").strip()
    file      = request.files.get("statement_file")

    if not file or not file.filename:
        flash("Please select a file to upload.", "danger")
        return redirect(url_for("statement_upload"))

    filename = file.filename.lower()
    file_bytes = file.read()

    if not file_bytes:
        flash("Uploaded file is empty.", "danger")
        return redirect(url_for("statement_upload"))

    from services.statement_parser import parse_csv_statement, parse_pdf_statement
    try:
        if filename.endswith(".pdf"):
            transactions = parse_pdf_statement(file_bytes, file.filename, family_id)
        elif filename.endswith((".csv", ".txt")):
            transactions = parse_csv_statement(file_bytes, family_id)
        else:
            flash("Unsupported file type. Please upload a CSV or PDF.", "danger")
            return redirect(url_for("statement_upload"))
    except Exception as e:
        app.logger.error(f"Statement parse error: {e}")
        flash(f"Could not parse the statement: {e}", "danger")
        return redirect(url_for("statement_upload"))

    if not transactions:
        if _METRICS:
            fmt = "pdf" if filename.endswith(".pdf") else "csv"
            STATEMENT_IMPORT.labels(bank=bank_name or "unknown", file_format=fmt, status="empty").inc()
        flash("No debit transactions found in the statement. "
              "Check the file format or try a different bank export.", "warning")
        return redirect(url_for("statement_upload"))

    upload_id = str(uuid.uuid4())
    db.save_statement_upload(upload_id, family_id, bank_name, file.filename, transactions)

    if _METRICS:
        fmt = "pdf" if filename.endswith(".pdf") else "csv"
        STATEMENT_IMPORT.labels(bank=bank_name or "unknown", file_format=fmt, status="success").inc()

    flash(f"✅ Found {len(transactions)} transactions. Review and add below.", "success")
    return redirect(url_for("statement_review", upload_id=upload_id))


@login_required
@app.route("/credit-cards/review/<upload_id>")
def statement_review(upload_id):
    """Review parsed statement transactions and add them to expenses."""
    upload = db.get_statement_upload(upload_id)
    if not upload:
        flash("Statement not found or expired.", "danger")
        return redirect(url_for("statement_upload"))

    transactions = upload["transactions"]
    categories   = db.get_all_categories()

    # Build category summary for the header cards
    cat_totals = {}
    total_amt  = 0.0
    pending    = 0
    for txn in transactions:
        if not txn.get("added"):
            pending += 1
        total_amt += txn["amount"]
        cat = txn.get("category", "Other")
        cat_totals[cat] = cat_totals.get(cat, 0) + txn["amount"]

    top_cats = sorted(cat_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    return render_template(
        "statement_review.html",
        upload=upload,
        transactions=transactions,
        categories=categories,
        total_amt=total_amt,
        pending=pending,
        top_cats=top_cats,
    )


@login_required
@app.route("/credit-cards/add-transaction", methods=["POST"])
def add_statement_transaction():
    """AJAX endpoint — add a single statement transaction to expenses."""
    data      = request.get_json(silent=True) or {}
    upload_id = data.get("upload_id", "")
    txn_id    = data.get("txn_id", "")
    category  = data.get("category", "Other")
    added_by  = session.get("admin_username") or session.get("member_name") or "Web"

    upload = db.get_statement_upload(upload_id)
    if not upload:
        return jsonify({"ok": False, "error": "Upload not found"}), 404

    # Find the transaction
    txn = next((t for t in upload["transactions"] if t["id"] == txn_id), None)
    if not txn:
        return jsonify({"ok": False, "error": "Transaction not found"}), 404

    if txn.get("added"):
        return jsonify({"ok": False, "error": "Already added"}), 409

    # Resolve family_id
    family_id = upload.get("family_id")

    # Add to expenses
    expense_id = db.add_expense(
        title     = txn["description"],
        amount    = txn["amount"],
        category  = category,
        date      = txn["date"],
        note      = f"Imported from {upload.get('bank_name', 'CC')} statement",
        added_by  = added_by,
        shop_name = txn.get("shop_name") or None,
        family_id = family_id,
    )

    db.mark_statement_transaction_added(upload_id, txn_id)

    if _METRICS:
        bank = upload.get("bank_name") or "unknown"
        STATEMENT_TXN_ADDED.labels(bank=bank).inc()
        EXPENSE_ADDED.labels(method="import", category=category).inc()
        EXPENSE_AMOUNT.labels(category=category).inc(txn["amount"])

    return jsonify({"ok": True, "expense_id": expense_id})
