# Expense Tracker — Deployment Guide

## What Was Added (Login System)

A full login system has been added to secure the dashboard:

- **Default credentials:** username `admin` / password `Admin@123`
- On first login you are **forced to change** both username and password before accessing any page
- All 22 routes are now protected — nobody can access the dashboard without logging in
- The `/whatsapp` webhook remains public (required for Twilio to work)
- Passwords are hashed with `werkzeug` (bcrypt-based) — never stored in plain text
- CSRF protection still applies to all forms

---

## Step 1 — First Run (Restart the App)

Stop the existing app if running (`Ctrl+C` in terminal), then:

```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
python3 app.py
```

The first startup will:
1. Add the `admin_credentials` table to your existing `expenses.db`
2. Seed the default admin account (`admin` / `Admin@123`)

---

## Step 2 — First Login & Mandatory Credential Change

1. Open **http://127.0.0.1:5001** in your browser
2. You'll be redirected to **http://127.0.0.1:5001/login**
3. Enter the default credentials:
   - **Username:** `admin`
   - **Password:** `Admin@123`
4. You will be **immediately redirected** to the Change Credentials page
5. Set your new username and password:
   - Username: minimum 3 characters
   - Password: minimum 8 characters (use a mix of letters, numbers, symbols)
6. Click **Save New Credentials**
7. You're now on the Dashboard — fully secured ✅

---

## Step 3 — Running with WhatsApp Bot (ngrok)

The auth system is compatible with your existing WhatsApp setup.
The `/whatsapp` endpoint is **excluded from login protection** intentionally.

**Terminal 1 (ngrok):**
```bash
ngrok http 5001
```

**Terminal 2 (Flask):**
```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
python3 app.py
```

---

## Changing Credentials Later

At any time, click **Credentials** in the sidebar footer (bottom-left), or visit:
```
http://127.0.0.1:5001/change-credentials
```

You'll need your **current password** to set a new one.

---

## Forgot Your Password?

If you forget your password, reset it from the Terminal:

```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
python3 - << 'EOF'
import database as db
from werkzeug.security import generate_password_hash

db.init_db()
new_hash = generate_password_hash("NewPassword123!")
conn = db.get_connection()
conn.execute(
    "UPDATE admin_credentials SET password_hash=?, must_change_password=1, username='admin' WHERE id=1",
    (new_hash,)
)
conn.commit()
conn.close()
print("✅ Password reset to: NewPassword123!")
print("   Username reset to: admin")
print("   You will be forced to change credentials on next login.")
EOF
```

Then log in with `admin` / `NewPassword123!` and you'll be prompted to set a new password.

---

## Security Summary

| Feature | Status |
|---|---|
| Login required for dashboard | ✅ All 22 routes protected |
| Password hashing (bcrypt) | ✅ Werkzeug |
| Forced credential change on first login | ✅ |
| CSRF protection on all forms | ✅ |
| Security headers (CSP, X-Frame, etc.) | ✅ Already present |
| WhatsApp webhook left public | ✅ Required for Twilio |
| Twilio signature validation | ✅ Already present |

---

## Files Changed

| File | What Changed |
|---|---|
| `database.py` | Added `admin_credentials` table + `get_admin_credentials()` + `update_admin_credentials()` |
| `app.py` | Added `login_required` decorator, `/login`, `/logout`, `/change-credentials` routes, `@login_required` on all 22 routes |
| `templates/login.html` | **New** — Login page with eye toggle & first-time hint |
| `templates/change_credentials.html` | **New** — Change credentials page with password strength meter |
| `templates/base.html` | Added logged-in user display, Credentials link, and Logout button in sidebar footer |
