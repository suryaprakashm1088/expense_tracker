# 💰 Family Expense Tracker

A **self-hosted** personal expense tracker with a WhatsApp bot so your family can log spending by just sending a message — no app to install. Everything runs on your own computer.

---

## What it does

| Feature | Description |
|---|---|
| 💬 **WhatsApp bot** | Family members text a Twilio number to log expenses |
| 📊 **Web dashboard** | Live charts, category breakdown, monthly trends |
| 📸 **Receipt scanning** | Send a receipt photo — local AI extracts items automatically |
| 💳 **Statement import** | Upload bank CSV or PDF — auto-categorises all transactions |
| 💰 **Budget planning** | Track income, fixed expenses, and projected savings |
| 🤖 **AI daily summary** | WhatsApp digest every night powered by Claude |
| 📈 **Monitoring** | Prometheus + Grafana dashboards + Loki logs |
| 💾 **Auto backup** | SQLite backup every night at 02:00 SGT, 30-day rotation |
| 👨‍👩‍👧 **Multi-member** | Invite codes or self-registration with admin approval |
| 🔒 **Web login** | Members log in to view reports; admin controls everything |

---

## Pick your setup path

### Which tunnel method?

| | **Option 1 — ngrok** | **Option 2 — Cloudflare Tunnel** |
|---|---|---|
| **Best for** | Trying it out, personal use | Permanent production setup |
| **Domain** | ❌ Not needed | ✅ Your own domain (~$10/yr) |
| **URL** | Free static subdomain (ngrok-free.app) | Your domain — permanent |
| **SSL** | Included | Included via Cloudflare |
| **Setup time** | ~15 min | ~45 min |
| **Cost** | Free | ~$10/year (domain only) |
| **Full guide** | 📄 [DEPLOY_NGROK.md](DEPLOY_NGROK.md) | 📄 [DEPLOY_CLOUDFLARE.md](DEPLOY_CLOUDFLARE.md) |

### Which Twilio plan?

Both options above work with either Twilio mode:

| | **Sandbox (free)** | **Paid number (~$1/mo)** |
|---|---|---|
| **Cost** | Free | ~$1/month |
| **Join step** | Each member sends a one-time join code | No join code — direct messaging |
| **Ideal for** | Testing, small family | Anyone can just message |

---

## Prerequisites — collect these before starting

- [ ] **Docker Desktop 4.27+** → [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)
- [ ] **Twilio account** (free) → [twilio.com](https://www.twilio.com)
- [ ] **ngrok account** (free, Option 1 only) → [ngrok.com](https://ngrok.com)
- [ ] **Cloudflare account** (free, Option 2 only) → [cloudflare.com](https://cloudflare.com)
- [ ] **Domain name** (~$10/yr, Option 2 only) → any registrar
- [ ] **Anthropic API key** *(optional — AI summaries + receipt cloud fallback)* → [console.anthropic.com](https://console.anthropic.com)
- [ ] **LM Studio** *(optional — local AI on Mac M-series)* → [lmstudio.ai](https://lmstudio.ai)

---

## Quick start

```bash
# 1. Clone the repo
git clone <your-repo-url>
cd expense_tracker

# 2. Create your environment file
cp .env.example .env
# Open .env and fill in values — see Environment Variables below

# 3. Start the app
docker compose -f docker-compose.local.yml up -d --build

# 4. Open the dashboard
open http://localhost:5001
# Log in with the one-time password shown on the login page
```

The WhatsApp bot needs a public tunnel — follow the guide for your chosen option.

---

## Environment variables

Copy `.env.example` → `.env` and fill in:

| Variable | Required | How to get it |
|---|---|---|
| `SECRET_KEY` | **Always** | Run: `python3 -c "import secrets; print(secrets.token_hex(64))"` |
| `TWILIO_ACCOUNT_SID` | WhatsApp bot | [console.twilio.com](https://console.twilio.com) → home page |
| `TWILIO_AUTH_TOKEN` | WhatsApp bot | Same page |
| `TWILIO_WHATSAPP_NUMBER` | WhatsApp bot | `whatsapp:+14155238886` (sandbox) or `whatsapp:+<paid-number>` |
| `DASHBOARD_URL` | WhatsApp bot | Your ngrok URL or `https://yourdomain.com` |
| `GRAFANA_ADMIN_PASSWORD` | Monitoring | Choose a strong password |
| `ANTHROPIC_API_KEY` | Optional | [console.anthropic.com](https://console.anthropic.com) |
| `CLOUDFLARE_TUNNEL_TOKEN` | Option 2 only | Cloudflare Zero Trust dashboard |

> ⚠️ Never commit `.env` to git. It is already in `.gitignore`.

---

## First login

On first startup, the login page shows a **one-time password (OTP)** in a green box:

- **Username:** `admin`
- **Password:** *(the OTP shown on screen)*

You are immediately prompted to set a new username and password. The OTP disappears permanently after that.

---

## WhatsApp bot commands

```
FairPrice 45.50             → add $45.50 under Food & Groceries
Grab 12 airport trip        → expense with note
[any receipt photo]         → AI scans and extracts all items

today                       → today's family spending
monthly                     → this month's category breakdown
mine                        → my expenses today
week                        → last 7 days
last                        → my last 5 entries
undo                        → delete my last entry
ai summary                  → AI-written monthly insight
help                        → full command list
```

Admin-only:
```
invite John                 → 24-hour invite code
invite John 7days           → invite code valid 7 days
members                     → list approved members
```

---

## AI setup (optional)

Receipt scanning uses a three-tier fallback — tries each in order:

| Priority | Engine | Setup |
|---|---|---|
| 1st | **LM Studio** (local, Mac GPU) | [lmstudio.ai](https://lmstudio.ai) — download, load a vision model, start Local Server |
| 2nd | **Ollama** (local, Mac GPU) | `brew install ollama && ollama pull llava:7b` |
| 3rd | **Claude Vision** (cloud) | Set `ANTHROPIC_API_KEY` in `.env` |

All AI is optional. The app works without any of these — receipt photos just won't be auto-scanned.

See [SETUP_DOCKER_AI.md](SETUP_DOCKER_AI.md) for details.

---

## Monitoring (optional)

```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up -d

# Grafana:    http://localhost:3000  (admin / your GRAFANA_ADMIN_PASSWORD)
# Prometheus: http://localhost:9090
```

The pre-built Grafana dashboard shows HTTP metrics, expense counts, WhatsApp volume, AI scan performance, and live container logs.

---

## Daily backup

The app automatically backs up the database every night at **02:00 SGT (18:00 UTC)**.

- Location: `./data/backups/expenses_YYYYMMDD_HHMMSS.db`
- Keeps the last 30 backups, deletes older ones automatically

**To restore:**
```bash
docker compose -f docker-compose.local.yml down
cp data/backups/expenses_20260101_020000.db data/expenses.db
docker compose -f docker-compose.local.yml up -d
```

---

## Member onboarding

**Invite code (instant):**
1. Dashboard → Onboarding → Generate code for the member
2. They send `JOIN <code>` to the WhatsApp bot → instantly approved

**Self-registration (approval queue):**
1. Member messages the bot → gets "waiting for approval"
2. You approve them on the Members page → they get a WhatsApp confirmation

---

## Project structure

```
expense_tracker/
├── app.py                      ← Entry point
├── app_metrics.py              ← Prometheus metric definitions
├── config.py                   ← Constants and env vars
├── database.py                 ← All SQLite operations
├── extensions.py               ← Flask app, CSRF, auth middleware
├── local_ai.py                 ← LM Studio + Ollama + Claude Vision
├── Dockerfile
├── docker-compose.local.yml    ← App + Cloudflare tunnel
├── .env                        ← Your secrets (never commit)
├── .env.example                ← Template
├── routes/                     ← Flask route handlers
├── services/                   ← Business logic
│   ├── whatsapp_bot.py         ← WhatsApp handling
│   ├── receipt.py              ← AI receipt scanning
│   ├── statement_parser.py     ← Bank statement CSV/PDF parsing
│   └── scheduler.py            ← Nightly backup + AI summary
├── templates/                  ← HTML templates
└── monitoring/                 ← Grafana + Prometheus + Loki stack
```

---

## Guides

| Guide | What it covers |
|---|---|
| [DEPLOY_NGROK.md](DEPLOY_NGROK.md) | **Option 1:** Full setup — ngrok, no domain needed |
| [DEPLOY_CLOUDFLARE.md](DEPLOY_CLOUDFLARE.md) | **Option 2:** Full setup — custom domain via Cloudflare |
| [SETUP_DOCKER_AI.md](SETUP_DOCKER_AI.md) | LM Studio + Ollama local AI setup |

---

## Tech stack

- **Flask + Gunicorn** (1 worker, 4 threads) + **SQLite**
- **Bootstrap 5 + Chart.js**
- **Twilio** — WhatsApp webhook
- **APScheduler** — nightly backup + AI summary jobs
- **LM Studio / Ollama / Claude** — AI tier stack
- **Prometheus + Grafana + Loki** — monitoring
- **Docker** — containerised deployment
- **ngrok or Cloudflare Tunnel** — public HTTPS for Twilio
