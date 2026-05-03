# Expense Tracker — Project Context for Claude

## What this project is
A Flask-based personal expense tracker with a WhatsApp bot integration.
Group members log expenses by texting a Twilio bot number.
All data is stored locally in SQLite.
The web dashboard shows charts, monthly summaries, budget planning, CC bills, and statement imports.
A full Prometheus + Grafana + Loki monitoring stack lives in `monitoring/`.

## How to run

**Docker (production — always use this):**
```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
docker compose -f docker-compose.local.yml up -d --build app
# → http://127.0.0.1:5001
```

**Rebuild only the app container (no downtime for tunnel):**
```bash
docker compose -f docker-compose.local.yml up -d --build app
```

**Monitoring stack (Prometheus + Grafana + Loki):**
```bash
docker compose -f monitoring/docker-compose.monitoring.yml up -d
# Grafana: http://localhost:3000  (admin / expenses123)
# Prometheus: http://localhost:9090
```

Port is **5001** (not 5000 — AirPlay Receiver occupies 5000 on macOS).

For the WhatsApp bot also run ngrok in a separate terminal:
```bash
ngrok http 5001
# Then update Twilio sandbox webhook URL to https://<ngrok-url>/whatsapp
```

---

## File structure

```
expense_tracker/
├── app.py              ← Thin entry point (imports + startup only, ~42 lines)
├── app_metrics.py      ← All Prometheus metric definitions (Counter, Histogram, Info)
├── config.py           ← All env vars + constants (MONTH_NAMES, CATEGORY_KEYWORDS, SG_CC_BANKS…)
├── extensions.py       ← Flask app instance, PrometheusMetrics init, CSRF, auth middleware
├── database.py         ← All SQLite operations (init_db, CRUD for all tables)
├── local_ai.py         ← LM Studio (primary vision) + Ollama (fallback) + Docker Model Runner (text)
├── requirements.txt
│
├── services/           ← Pure business logic (no Flask routes here)
│   ├── __init__.py
│   ├── ai_clients.py        ← get_twilio_client(), get_anthropic_client(), get_category_from_ai()
│   ├── expense_parser.py    ← parse_expense_message()
│   ├── cc_parser.py         ← parse_cc_bill_message(), uses SG_CC_BANKS + CC_TOKENS from config
│   ├── statement_parser.py  ← parse_csv_statement(), parse_pdf_statement() — CC statement file import
│   ├── invite.py            ← generate_code(), parse_expiry(), handle_join_code()
│   ├── receipt.py           ← handle_receipt_photo(), _scan_receipt_image() (LM Studio→Ollama→Claude)
│   ├── scheduler.py         ← send_daily_summary(), start_scheduler()  (APScheduler, 20:00 SGT)
│   └── whatsapp_bot.py      ← twiml(), handle_pending_response(), build_whatsapp_reply()
│
├── routes/             ← Flask route handlers only (import from services/ and database)
│   ├── __init__.py     ← imports all route modules so decorators register at startup
│   ├── auth.py         ← /login  /logout  /change-credentials
│   ├── expenses.py     ← /  /add  /expenses  /edit/<id>  /delete/<id>  /receipts
│   ├── summary.py      ← /summary  /api/category-detail  /api/monthly-data  /api/ai-summary  /api/ai-status
│   ├── budget.py       ← /budget  /budget/income/delete/<id>  /budget/fixed/delete/<id>
│   ├── credit_cards.py ← /credit-cards  /credit-cards/delete/<id>
│   │                      /credit-cards/upload  /credit-cards/review/<id>
│   │                      /credit-cards/add-transaction  (AJAX)
│   ├── admin.py        ← /categories  /members  /onboarding  /shop-mappings  /unknown-contacts  /img/<uid>
│   └── whatsapp.py     ← /whatsapp  /health
│
├── static/
│   ├── css/            ← (reserved for future extracted CSS)
│   └── js/
│       └── app.js      ← CAT_COLORS dict + getCatColor / getCatLight / getCatIcon helpers
│
├── templates/
│   ├── base.html               ← Sidebar, Bootstrap, Chart.js, loads static/js/app.js
│   ├── index.html              ← Dashboard (stat cards, pie + bar charts, recent expenses)
│   ├── add.html                ← Add expense form (duplicate warning card)
│   ├── edit.html               ← Edit expense form
│   ├── expenses.html           ← All expenses with filters
│   ├── summary.html            ← Monthly summary + accordion category drill-down
│   ├── budget.html             ← Income + fixed expenses + projected savings
│   ├── credit_cards.html       ← CC bill tracking per member per bank
│   ├── statement_upload.html   ← Upload bank statement (CSV / PDF)
│   ├── statement_review.html   ← Review parsed transactions, add to expenses with + button
│   ├── categories.html         ← Add / edit / delete categories (admin)
│   ├── edit_category.html      ← Edit a single category
│   ├── members.html            ← WhatsApp member approval + web login management
│   ├── onboarding.html         ← Family setup + invite code generator
│   ├── shop_mappings.html      ← Shop → category auto-mapping table
│   ├── receipts.html           ← Receipt scan history
│   ├── unknown_contacts.html   ← Unknown WhatsApp contacts + security alerts
│   ├── login.html              ← Login page
│   └── change_credentials.html
│
└── monitoring/                 ← Full observability stack (Prometheus + Grafana + Loki)
    ├── docker-compose.monitoring.yml
    ├── prometheus/
    │   └── prometheus.yml      ← Scrapes http://host.docker.internal:5001/metrics every 15s
    ├── loki/
    │   └── loki-config.yml     ← Log aggregation backend
    ├── promtail/
    │   └── promtail-config.yml ← Ships Docker container logs → Loki
    └── grafana/
        ├── provisioning/
        │   ├── datasources/ds.yml     ← Auto-wires Prometheus + Loki datasources
        │   └── dashboards/config.yml  ← Dashboard file provider
        └── dashboards/
            └── expense-tracker.json  ← Pre-built dashboard (auto-loads on startup)
```

---

## Dependency order (no circular imports)

```
config.py
  └─ database.py
  └─ app_metrics.py          (prometheus_client only — no project imports)
  └─ extensions.py  (imports config + database, creates Flask app, inits PrometheusMetrics)
       └─ services/ai_clients.py   (imports extensions.app for logger)
       └─ services/expense_parser.py
       └─ services/cc_parser.py
       └─ services/statement_parser.py  (imports database + config)
       └─ services/invite.py
       └─ services/receipt.py      (imports extensions.app + ai_clients + app_metrics)
       └─ services/scheduler.py    (imports extensions.app + ai_clients)
       └─ services/whatsapp_bot.py (imports all services above + app_metrics)
            └─ routes/auth.py
            └─ routes/expenses.py      (imports app_metrics)
            └─ routes/summary.py
            └─ routes/budget.py
            └─ routes/credit_cards.py  (imports app_metrics)
            └─ routes/admin.py         (imports services/invite + services/ai_clients)
            └─ routes/whatsapp.py      (imports services/whatsapp_bot + services/receipt + services/invite)
                 └─ app.py             (imports extensions.app + routes)
```

---

## Database schema

### `expenses`
| column      | type    | notes                                       |
|-------------|---------|---------------------------------------------|
| id          | INTEGER | PK                                          |
| title       | TEXT    | expense name                                |
| amount      | REAL    | in S$                                       |
| category    | TEXT    | matches categories.name                     |
| date        | TEXT    | YYYY-MM-DD                                  |
| note        | TEXT    | optional                                    |
| added_by    | TEXT    | "Web" or WhatsApp member name               |
| shop_name   | TEXT    | optional; normalised shop name              |
| label       | TEXT    | optional free-text label                    |
| receipt_id  | TEXT    | UUID linking items to a receipt scan        |
| family_id   | INTEGER | FK → families.id                            |

### `categories`
| column     | type    | notes                  |
|------------|---------|------------------------|
| id         | INTEGER | PK                     |
| name       | TEXT    | unique                 |
| icon       | TEXT    | emoji                  |
| sort_order | INTEGER | display order          |

### `members`
| column           | type    | notes                                   |
|------------------|---------|-----------------------------------------|
| id               | INTEGER | PK                                      |
| name             | TEXT    | WhatsApp display name                   |
| whatsapp_number  | TEXT    | `whatsapp:+6591234567`                  |
| is_approved      | INTEGER | 0 = pending, 1 = approved               |
| is_admin         | INTEGER | 0 = member, 1 = admin                   |
| family_id        | INTEGER | FK → families.id                        |
| nickname         | TEXT    | display name override                   |
| password_hash    | TEXT    | for web login (optional)                |

### `families`
| column | type    | notes |
|--------|---------|-------|
| id     | INTEGER | PK    |
| name   | TEXT    |       |

### `pending_receipts`
Stores JSON pending state per WhatsApp sender phone number.
Types: `receipt`, `category_ask`, `duplicate_confirm`, `group_dup_confirm`.

### `statement_uploads`
| column       | type    | notes                                              |
|--------------|---------|----------------------------------------------------|
| id           | TEXT    | UUID (PK)                                          |
| family_id    | INTEGER | FK → families.id                                   |
| bank_name    | TEXT    | e.g. "DBS"                                         |
| filename     | TEXT    | original uploaded filename                         |
| uploaded_at  | TEXT    | ISO timestamp                                      |
| transactions | TEXT    | JSON array of transaction dicts (see below)        |

Each transaction dict:
```json
{
  "id": "uuid",
  "date": "YYYY-MM-DD",
  "description": "NTUC FAIRPRICE",
  "amount": 45.80,
  "category": "Food & Groceries",
  "shop_name": "NTUC FairPrice",
  "added": false
}
```

### `credit_card_bills`
| column      | type    | notes               |
|-------------|---------|---------------------|
| id          | INTEGER | PK                  |
| bank_name   | TEXT    | e.g. "DBS"          |
| amount      | REAL    | in S$               |
| member_name | TEXT    |                     |
| date        | TEXT    | YYYY-MM-DD          |
| month       | INTEGER |                     |
| year        | INTEGER |                     |
| note        | TEXT    | optional            |
| family_id   | INTEGER |                     |

### `income_entries` / `fixed_expenses`
Standard budget tables — description, amount, category, family_id, is_active.

---

## Key design decisions

**No Flask Blueprints** — Routes register directly on `app` (from `extensions.py`).
This means `url_for('endpoint_name')` in all templates stays unchanged.

**Auth flow:**
- `extensions.py` registers `@app.before_request` for login enforcement.
- `login_required` and `admin_required` decorators are defined there too.
- Import them with `from extensions import login_required, admin_required`.

**CSRF — supports both form field and X-CSRFToken header:**
- HTML forms: send `<input name="_csrf_token">` hidden field.
- AJAX/JSON requests: send `X-CSRFToken: <token>` HTTP header.
- Both are checked in `extensions.py → csrf_protect()`. Do NOT add JSON endpoints to CSRF_EXEMPT — use the header instead.

**AI vision stack — three-tier fallback (`services/receipt.py`, `services/statement_parser.py`):**
1. LM Studio (qwen3-vl-4b) — OpenAI-compatible local server at `http://host.docker.internal:1234/v1`
2. Ollama (llava) — local Metal GPU at `http://host.docker.internal:11434`
3. Claude Vision API — cloud fallback (requires `ANTHROPIC_API_KEY`)
Each engine's scan duration and success/fail is recorded in Prometheus via `app_metrics.py`.

**Statement import (`services/statement_parser.py`):**
- CSV: auto-detects bank format (DBS/OCBC/UOB/Citi/SCB/generic) from header row.
- PDF: pdfplumber text extraction first; if < 2 results, falls back to AI vision.
- Parsed transactions stored in `statement_uploads` table as JSON blob with UUID key.
- Review page (`/credit-cards/review/<id>`) uses AJAX to add individual rows to expenses.

**Prometheus metrics (`app_metrics.py`):**
- All metrics imported from `app_metrics.py`. Never define metrics inline in routes.
- Metrics are guarded with `try/except ImportError` so the app starts even if `prometheus-flask-exporter` is not installed.
- `/metrics` endpoint is in `PUBLIC_ENDPOINTS` — no login required (Prometheus must reach it).

**Group duplicate detection** (`database.py → check_group_duplicate`):
- Checks same amount (±0.01) + same date + same family + same shop/title.
- Shop names are normalised: `_norm()` strips whitespace + lowercases so "FairPrice" = "Fair Price".
- Web form: shows warning card in `add.html`; user must tick confirm.
- WhatsApp: saves `group_dup_confirm` pending state; user replies YES/NO.

**Budget summary projection** (`database.py → get_budget_summary`):
- `projected_net = total_income − total_fixed − variable_total`.

**Daily summary scheduler** (`services/scheduler.py`):
- APScheduler background job at 12:00 UTC = 20:00 SGT.
- Sends Claude Haiku AI summary to all approved family members via WhatsApp.

---

## Common task recipes

### Add a new expense field
1. `database.py` → `init_db()` → ADD COLUMN + `ALTER TABLE` fallback
2. `database.py` → update `add_expense()` and `update_expense()` signatures
3. `routes/expenses.py` → update `add()` and `edit()` form parsing
4. `templates/add.html` and `templates/edit.html` → add form fields
5. `templates/expenses.html` → add column to table

### Add a new WhatsApp bot command
1. `services/whatsapp_bot.py` → `build_whatsapp_reply()` → add `if text == "cmd":` block + call `_finish(reply, msg_type="command")`
2. Same function → update the HELP text block
3. `templates/members.html` → add row to the bot commands reference table

### Add a new web page / route
1. `routes/<appropriate_module>.py` → add `@app.route(...)` function
2. Create `templates/yourpage.html` extending `base.html`
3. `templates/base.html` → add nav link in sidebar
4. `config.py` → add endpoint name to `MEMBER_ALLOWED` (or `ADMIN_ONLY`)

### Add an AJAX/JSON POST endpoint
- Do NOT add to `CSRF_EXEMPT`. Instead, in the JS send `"X-CSRFToken": csrf_token` as a fetch header.
- The `csrf_protect` before_request checks both the form field and this header.

### Add a new Prometheus metric
1. `app_metrics.py` → define the Counter/Histogram with `expense_tracker_` prefix
2. Import in the route/service file: `from app_metrics import MY_METRIC`
3. Wrap in `try/except ImportError` guard (pattern already used in all instrumented files)
4. Call `.inc()` / `.observe()` at the right point
5. Add a panel to `monitoring/grafana/dashboards/expense-tracker.json` or create it in the Grafana UI

### Change statement import parsing (CSV format)
- `services/statement_parser.py` → `_detect_csv_format()` to add new bank
- `services/statement_parser.py` → `_extract_row_fields()` to add column mapping for that bank
- `config.py` → `SG_CC_BANKS` if the bank is new

### Add a new Singapore bank to CC tracking
- `config.py` → `SG_CC_BANKS` dict (short token → display name)
- `templates/credit_cards.html` → add CSS class + colour in the `BANK_COLORS` JS block if needed

### Change admin middleware (CSRF, login enforcement, headers)
- `extensions.py`

### Change the daily WhatsApp summary message
- `services/scheduler.py` → `send_daily_summary()` → edit the AI prompt

### Update the monitoring dashboard
- Edit `monitoring/grafana/dashboards/expense-tracker.json` — Grafana hot-reloads it every 30s.
- Or make changes in the Grafana UI at http://localhost:3000 and export the JSON.
- Prometheus query language reference: https://prometheus.io/docs/prometheus/latest/querying/basics/

---

## Files to read for each task type

| Task | Files to read |
|------|--------------|
| Dashboard changes | `routes/expenses.py` (index route), `templates/index.html` |
| Expense form changes | `routes/expenses.py` (add/edit routes), `templates/add.html`, `templates/edit.html` |
| WhatsApp bot changes | `services/whatsapp_bot.py` (build_whatsapp_reply, handle_pending_response) |
| Category changes | `database.py`, `routes/admin.py`, `templates/categories.html` |
| Member/security changes | `database.py` (members section), `routes/admin.py`, `extensions.py` |
| Database schema changes | `database.py` (init_db, add_expense, etc.) |
| Statement import changes | `services/statement_parser.py`, `routes/credit_cards.py`, `templates/statement_review.html` |
| AI / receipt scan changes | `services/receipt.py`, `local_ai.py` |
| Styling/layout changes | `templates/base.html` (CSS variables, sidebar) |
| Chart changes | `templates/index.html` or `templates/summary.html` (Chart.js blocks) |
| Prometheus metrics | `app_metrics.py`, then the route/service file where it's recorded |
| Monitoring dashboard | `monitoring/grafana/dashboards/expense-tracker.json` |
| Monitoring stack config | `monitoring/docker-compose.monitoring.yml`, `monitoring/prometheus/prometheus.yml` |
| CSRF / auth middleware | `extensions.py` |
| Access control (who can see what) | `config.py` → `PUBLIC_ENDPOINTS`, `MEMBER_ALLOWED`, `ADMIN_ONLY`, `CSRF_EXEMPT` |

---

## Known gotchas

- **Port 5001** always (macOS AirPlay uses 5000).
- **debug=False** keeps Flask single-process — required for stable ngrok tunnelling.
- **SQLite disk I/O error** in the bash sandbox: expected, the sandbox can't write to the mounted filesystem. Always test against the real machine.
- **ngrok free tier** changes URL on every restart — update Twilio webhook URL each time.
- **`url_for` in templates** uses plain endpoint names (not Blueprint-prefixed), because no Blueprints are used.
- **CSRF for AJAX**: Do NOT use CSRF_EXEMPT for JSON endpoints. Send `X-CSRFToken` header from JS instead.
- **Prometheus import guard**: All files that import from `app_metrics` wrap it in `try/except ImportError`. If `prometheus-flask-exporter` is not installed, the app still starts — metrics are just skipped.
- **`/metrics` is public**: It's in `PUBLIC_ENDPOINTS` so Prometheus can scrape it without login. Do not put sensitive data in metric label values.
- **pdfplumber**: Used for PDF statement parsing. If not installed, falls back to AI. Listed in `requirements.txt` — included in the Docker build.
- **LM Studio server must be started manually**: In LM Studio → Local Server tab → Start Server. It doesn't auto-start. Test with `curl http://localhost:1234/v1/models`.
- **Monitoring stack is separate from the app**: Run with `docker compose -f monitoring/docker-compose.monitoring.yml up -d`. The monitoring containers reach the Flask app via `host.docker.internal:5001`.
