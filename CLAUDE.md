# Expense Tracker — Project Context for Claude

## What this project is
A Flask-based personal expense tracker with a WhatsApp bot integration. Group members can log expenses by sending WhatsApp messages to a Twilio bot number. All data is stored locally in SQLite. The web dashboard provides charts, filters, monthly summaries, category management, and member approval.

## How to run
```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
python3 app.py
# Open http://127.0.0.1:5001
```
Port is **5001** (not 5000 — AirPlay Receiver occupies 5000 on macOS).

For WhatsApp bot to work, also run in a separate terminal:
```bash
ngrok http 5001
```
Then update the Twilio sandbox webhook URL to `https://<ngrok-url>/whatsapp`.

## Tech stack
- **Flask** — web framework
- **SQLite** — local database (`expenses.db` in project root)
- **Bootstrap 5** + **Bootstrap Icons** — UI (CDN)
- **Chart.js** — pie, bar, and line charts (CDN)
- **Twilio** — WhatsApp bot webhook receiver
- **ngrok** — public tunnel for Twilio webhook

## File structure
```
expense_tracker/
├── app.py              — All Flask routes
├── database.py         — All SQLite operations
├── expenses.db         — SQLite database (auto-created on first run)
├── requirements.txt    — flask, twilio
├── run.sh              — Mac/Linux launcher
├── run_windows.bat     — Windows launcher
├── WHATSAPP_SETUP.md   — Twilio + ngrok setup guide
├── CLAUDE.md           — This file
└── templates/
    ├── base.html           — Sidebar layout, Bootstrap, Chart.js, shared JS
    ├── index.html          — Dashboard (stat cards, pie chart, bar chart, recent)
    ├── add.html            — Add expense form
    ├── edit.html           — Edit expense form
    ├── expenses.html       — View/filter all expenses
    ├── summary.html        — Monthly summary (pie, line chart, insights)
    ├── categories.html     — Add/edit/delete categories
    ├── edit_category.html  — Edit a single category
    └── members.html        — WhatsApp member approval management
```

## Database schema

### `expenses`
| column     | type    | notes                          |
|------------|---------|--------------------------------|
| id         | INTEGER | PK autoincrement               |
| title      | TEXT    | expense name                   |
| amount     | REAL    | in USD ($)                     |
| category   | TEXT    | matches categories.name        |
| date       | TEXT    | YYYY-MM-DD                     |
| note       | TEXT    | optional                       |
| added_by   | TEXT    | "Web" or WhatsApp member name  |

### `categories`
| column     | type    | notes                          |
|------------|---------|--------------------------------|
| id         | INTEGER | PK autoincrement               |
| name       | TEXT    | unique                         |
| icon       | TEXT    | emoji e.g. 🛒                  |
| sort_order | INTEGER | display order                  |

Default categories seeded on first run: Food & Groceries, Outside Food, Transport, Shopping, Bills & Utilities, Entertainment, Other.

### `members`
| column           | type    | notes                              |
|------------------|---------|------------------------------------|
| id               | INTEGER | PK autoincrement                   |
| name             | TEXT    | WhatsApp display name              |
| whatsapp_number  | TEXT    | format: `whatsapp:+1234567890`     |
| is_approved      | INTEGER | 0 = pending, 1 = approved          |
| added_on         | TEXT    | YYYY-MM-DD                         |

## Key design decisions

**Member approval flow:**
- When a new number messages the bot → auto-registered as `is_approved=0` (pending)
- Admin must go to `/members` and click Approve
- Members added manually from the dashboard → `is_approved=1` (approved immediately)

**Categories are dynamic:**
- Stored in DB, not hardcoded
- Managed via `/categories` page (add, edit, delete)
- Deleting a category does NOT delete expenses — they keep the old category label

**Currency:** USD ($). All display uses `"{:,.2f}".format(amount)` with `$` prefix.

**WhatsApp message parsing** (`build_whatsapp_reply` in app.py):
- Supported commands: `add`, `summary`, `total`, `today`, `recent`, `help`
- `add food 500 lunch` or `food 500 lunch` or `500 food lunch` all work
- Category matched via `CATEGORY_KEYWORDS` dict in app.py
- Unrecognised messages → falls through to `parse_expense_message()` → tries to extract amount + category

**Port:** Always use 5001. macOS AirPlay Receiver occupies 5000.

## Web routes

| Method | Route                        | Purpose                        |
|--------|------------------------------|--------------------------------|
| GET    | `/`                          | Dashboard                      |
| GET/POST | `/add`                     | Add expense                    |
| GET    | `/expenses`                  | View/filter expenses           |
| GET/POST | `/edit/<id>`               | Edit expense                   |
| POST   | `/delete/<id>`               | Delete expense                 |
| GET    | `/summary`                   | Monthly summary + charts       |
| GET    | `/categories`                | List + add categories          |
| POST   | `/categories/add`            | Add category                   |
| GET/POST | `/categories/edit/<id>`    | Edit category                  |
| POST   | `/categories/delete/<id>`    | Delete category                |
| GET    | `/members`                   | WhatsApp member management     |
| POST   | `/members/add`               | Add member (approved)          |
| POST   | `/members/toggle/<id>`       | Toggle approval status         |
| POST   | `/members/delete/<id>`       | Remove member                  |
| GET/POST | `/whatsapp`                | Twilio webhook                 |
| GET    | `/api/monthly-data`          | JSON API for chart refresh     |

## Common future tasks

**Add a new field to expenses (e.g. receipt photo):**
1. Add column in `init_db()` in database.py with `ALTER TABLE` fallback
2. Update `add_expense()` and `update_expense()` signatures
3. Update add.html and edit.html forms
4. Update expenses.html table

**Add a new WhatsApp command:**
1. Add a new `if text == "command":` block in `build_whatsapp_reply()` in app.py
2. Add it to the help text in the same function
3. Add it to the bot commands reference table in members.html

**Add a new category keyword for WhatsApp:**
- Edit `CATEGORY_KEYWORDS` dict near the top of app.py

**Change currency back to INR (₹):**
- Replace `$` with `₹` across all templates and app.py flash messages
- Replace `en-US` with `en-IN` in JS toLocaleString calls

**Deploy to a server (stop needing ngrok):**
- Use Railway, Render, or a VPS
- Set `debug=False` (already done)
- Use gunicorn: `pip install gunicorn && gunicorn app:app -b 0.0.0.0:5001`
- Set Twilio webhook to the permanent server URL

## Known issues / gotchas
- ngrok free tier URL changes every restart → must update Twilio webhook URL each time
- SQLite doesn't work well on network-mounted/NFS drives — keep expenses.db on local disk
- Flask debug mode starts 2 processes; debug=False avoids this confusion with ngrok
- macOS port 5000 is taken by AirPlay Receiver — always use 5001
