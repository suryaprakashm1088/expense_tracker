# Setup Guide — Option 2: Custom Domain via Cloudflare Tunnel

Run the Expense Tracker permanently on **your own computer** behind your own domain. The URL never changes, SSL is handled by Cloudflare, and you don't need to open any ports on your router.

```
WhatsApp → Twilio → Cloudflare (your domain, SSL) → Tunnel → your computer → Flask app → SQLite DB
```

**Cost:** ~$10/year for the domain. Everything else is free.

---

## Before you start — choose your Twilio plan

| | **Sandbox (free)** | **Paid number (~$1/mo)** |
|---|---|---|
| Cost | Free | ~$1/month |
| Member join step | Each member sends a one-time `join <code>` message | No join code — members text directly |
| WhatsApp number | Shared Twilio test number | Your own dedicated number |
| Best for | Testing while setting up | Long-term family use |

You choose this in Part 2. The rest of the setup is identical.

---

## Part 1 — Domain + Cloudflare

### Step 1 — Buy a domain

**Easiest (recommended):** Buy directly from Cloudflare — no nameserver changes needed.
1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) → **Domain Registration** → **Register Domains**
2. Search for a domain (e.g. `familyexpenses.com`) — costs ~$8–15/year
3. Purchase it

**Alternative:** Buy from Namecheap, GoDaddy, or any registrar, then follow Step 2.

### Step 2 — Point your domain to Cloudflare DNS (skip if you bought from Cloudflare)

1. Create a free Cloudflare account at [cloudflare.com](https://cloudflare.com)
2. Click **Add a site** → enter your domain → choose **Free plan**
3. Cloudflare scans existing DNS records and shows you two nameservers:
   ```
   aria.ns.cloudflare.com
   bob.ns.cloudflare.com
   ```
4. Log into your domain registrar → find **Nameservers** → replace them with Cloudflare's two
5. Wait 5–60 minutes for propagation. Cloudflare emails you when it's active.

---

## Part 2 — Twilio setup

### Step 3 — Create a Twilio account

1. Go to [twilio.com](https://www.twilio.com) → **Sign up** (free)
2. Verify your email and phone number

### 2A — Sandbox setup (free, start here)

1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message**
2. Note:
   - **Sandbox number** (e.g. `+1 415 523 8886`)
   - **Join code** (e.g. `join silver-flame`)
3. Your `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+14155238886`

> Members must send `join silver-flame` to the sandbox number once before using the bot.

### 2B — Paid number setup (~$1/month)

1. Twilio Console → **Phone Numbers → Buy a Number**
2. Filter by **WhatsApp** capability → purchase a number
3. Go to **Messaging → Senders → WhatsApp Senders** → add your number
4. Twilio sends a WhatsApp verification code to that number — approve it
5. Your `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+<your-number>`

> ⚠️ WhatsApp Business API approval takes **1–3 business days**. The sandbox is available immediately — start with sandbox and switch later.

---

## Part 3 — Cloudflare Tunnel

### Step 4 — Create the tunnel

1. Go to [one.dash.cloudflare.com](https://one.dash.cloudflare.com)
2. Left sidebar → **Networks → Tunnels → Add a tunnel**
3. Select **Cloudflared** as connector type → **Next**
4. Name your tunnel (e.g. `expense-tracker`) → **Save tunnel**
5. On the next screen, click the **Docker** tab
6. You'll see a command like:
   ```
   docker run cloudflare/cloudflared:latest tunnel --no-autoupdate run --token eyJhIjoiZ...
   ```
7. **Copy only the token** — the long string after `--token`. This is your `CLOUDFLARE_TUNNEL_TOKEN`.

> ⚠️ **Use the Zero Trust dashboard Docker tab** — not the CLI `cloudflared tunnel token` command. They generate different token types. Only the dashboard connector token works here.

### Step 5 — Add public hostname to the tunnel

Still in the tunnel editor, click **Public Hostnames** tab → **Add a public hostname**:

| Field | Value |
|---|---|
| Subdomain | *(leave blank for root domain)* |
| Domain | `yourdomain.com` |
| Type | `HTTP` |
| URL | `expense_tracker:5001` |

Click **Save hostname**.

> Use `expense_tracker:5001` — this is the Docker container name, not `localhost`. This is required because the tunnel runs inside Docker and communicates over Docker's internal network.

**Optional — add www as well:**

| Field | Value |
|---|---|
| Subdomain | `www` |
| Domain | `yourdomain.com` |
| Type | `HTTP` |
| URL | `expense_tracker:5001` |

---

## Part 4 — Configure the app

### Step 6 — Get the code

```bash
git clone <your-repo-url>
cd expense_tracker
```

### Step 7 — Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` and fill in:

```bash
# ── Twilio ──────────────────────────────────────────────────────────────────
# Find Account SID and Auth Token at: https://console.twilio.com (home page)
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Sandbox:  whatsapp:+14155238886
# Paid:     whatsapp:+<your-purchased-number>
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# ── Flask ────────────────────────────────────────────────────────────────────
FLASK_ENV=production

# REQUIRED — generate this, do not leave as placeholder:
#   python3 -c "import secrets; print(secrets.token_hex(64))"
SECRET_KEY=paste-64-char-hex-here

# ── Your permanent domain ─────────────────────────────────────────────────
DASHBOARD_URL=https://yourdomain.com

# ── Cloudflare Tunnel ────────────────────────────────────────────────────────
# Token from Step 4 above (Zero Trust dashboard → Docker tab)
CLOUDFLARE_TUNNEL_TOKEN=eyJhIjoiZ...

# ── Monitoring ───────────────────────────────────────────────────────────────
GRAFANA_ADMIN_PASSWORD=choose-a-strong-password

# ── Optional — AI summaries + receipt cloud fallback ─────────────────────────
# ANTHROPIC_API_KEY=sk-ant-api03-...
```

> 🔑 **SECRET_KEY is required.** Generate it:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(64))"
> ```

### Step 8 — Install Docker Desktop

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop).

- **Mac:** Open Docker Desktop and wait for the whale icon to stop animating.
- **Windows:** Enable WSL 2 integration when prompted.

---

## Part 5 — Start the app

### Step 9 — Build and start

```bash
docker compose -f docker-compose.local.yml up -d --build
```

First build takes 3–5 minutes. Watch the logs:

```bash
docker logs expense_tracker -f     # Flask app
docker logs expense_cloudflared -f # Cloudflare tunnel
```

The tunnel log should show:
```
INF Registered tunnel connection connIndex=0 ...
```

Both containers should be `Up`:
```bash
docker ps
# expense_tracker       Up X seconds
# expense_cloudflared   Up X seconds
```

### Step 10 — First login

Open `https://yourdomain.com` in your browser.

You'll see a **green box with a one-time password (OTP)**. Log in with:
- **Username:** `admin`
- **Password:** *(the OTP shown on screen)*

You are immediately prompted to set a permanent username and password.

---

## Part 6 — Connect Twilio

### Step 11 — Set the WhatsApp webhook

**For Sandbox:**
1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message → Sandbox settings**
2. Set **"When a message comes in"** to:
   ```
   https://yourdomain.com/whatsapp
   ```
3. Method: **HTTP POST** → **Save**

**For Paid number:**
1. Twilio Console → **Phone Numbers → Manage → Active Numbers** → click your number
2. Under **Messaging → "A message comes in"**, paste:
   ```
   https://yourdomain.com/whatsapp
   ```
3. Method: **HTTP POST** → **Save**

### Step 12 — Test the bot

**Sandbox:** First send `join silver-flame` to `+1 415 523 8886`, then send `help`

**Paid number:** Just send `help` to your number

You should get a reply within a few seconds.

---

## Part 7 — Add family members

### Step 13 — Onboard members

**Via invite code (recommended):**
1. Dashboard → **Onboarding** → Generate a code for each member
2. Send them: *"Message +1 415 523 8886 with: `JOIN <code>`"*

**Via self-registration:**
1. Member messages the bot → they get "Waiting for approval"
2. You approve them on the **Members** page

**Sandbox only — share join instructions with everyone:**

> "To join our expense tracker:
> 1. Save this number: **+1 415 523 8886**
> 2. Send it this message: **join silver-flame**
> 3. Then message `help` to see how to log expenses"

---

## Part 8 — Monitoring (optional)

### Step 14 — Start Grafana + Prometheus

```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up -d
```

Open [http://localhost:3000](http://localhost:3000):
- Username: `admin`
- Password: your `GRAFANA_ADMIN_PASSWORD`

The **Expense Tracker** dashboard loads automatically.

> Grafana and Prometheus run on localhost only — they are not exposed through the Cloudflare tunnel, which is correct. Monitoring is for your eyes only.

---

## Part 9 — AI receipt scanning (optional)

### LM Studio (best, local, Mac)

1. Download [lmstudio.ai](https://lmstudio.ai)
2. Search for and download a vision model (e.g. `qwen2.5-vl-7b-instruct`)
3. Go to **Local Server** tab → **Start Server**

The app is pre-configured to use LM Studio at `http://localhost:1234`. No `.env` changes needed.

### Ollama (fallback, local)

```bash
brew install ollama
ollama serve
ollama pull llava:7b
```

### Claude Vision (cloud fallback)

Uncomment in `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## Daily operation

### The app auto-restarts

Both containers have `restart: unless-stopped`. After Docker Desktop starts (on boot or manually), they restart automatically. You don't need to do anything daily.

### Manual start/stop

```bash
# Start
docker compose -f docker-compose.local.yml up -d

# Stop
docker compose -f docker-compose.local.yml down

# Logs
docker logs expense_tracker -f
docker logs expense_cloudflared -f
```

### Rebuild after code changes

```bash
docker compose -f docker-compose.local.yml up -d --build app
```

### What happens if your computer restarts

1. Docker Desktop starts automatically (if set to launch on login)
2. Both containers (`expense_tracker` + `expense_cloudflared`) restart automatically
3. The Cloudflare tunnel reconnects — your domain works again within seconds

---

## ⚠️ Checklist — things people commonly miss

- [ ] `SECRET_KEY` generated (not the placeholder text)
- [ ] `GRAFANA_ADMIN_PASSWORD` set to something real
- [ ] `CLOUDFLARE_TUNNEL_TOKEN` is from the **Zero Trust dashboard Docker tab** (not CLI)
- [ ] Tunnel hostname URL is `expense_tracker:5001` (not `localhost:5001`)
- [ ] Twilio webhook URL ends in `/whatsapp` and uses `HTTP POST`
- [ ] `DASHBOARD_URL` in `.env` matches your real domain
- [ ] Sandbox members sent the `join <code>` message (one-time per device)
- [ ] If paid Twilio number — WhatsApp Business API approval done (1–3 days)
- [ ] Domain nameservers point to Cloudflare (if not bought from Cloudflare)
- [ ] `ANTHROPIC_API_KEY` set if you want AI summaries

---

## Troubleshooting

| Problem | Solution |
|---|---|
| Site not loading | `docker logs expense_cloudflared` — look for connection errors |
| "Provided tunnel token is not valid" | Used the CLI token — go back to Zero Trust dashboard → Docker tab |
| "AAAA or CNAME already exists" error | Delete the conflicting DNS record in Cloudflare before adding in tunnel |
| App loads but bot doesn't reply | Check Twilio webhook is `https://yourdomain.com/whatsapp` with POST |
| "Not a member" reply | Member not approved — check Members page in dashboard |
| Sandbox member can't use bot | They haven't sent `join <code>` yet |
| Receipt scan fails | Check LM Studio Local Server is started; or set `ANTHROPIC_API_KEY` |
| App slow to load | Normal on first request after a long idle — gunicorn warms up in a second |
| Container not starting | `docker compose -f docker-compose.local.yml logs` to see the full error |

---

## Moving to a different computer

The Cloudflare tunnel token is tied to your tunnel (not your computer), so migration is easy:

```bash
# Old computer
docker compose -f docker-compose.local.yml down

# Copy expense_tracker/ folder to new computer (including ./data/ and .env)

# New computer — install Docker Desktop, then:
docker compose -f docker-compose.local.yml up -d --build
```

Your domain URL stays the same. Your data is preserved in `./data/expenses.db`.

---

## Upgrading the app

```bash
cd expense_tracker
git pull
docker compose -f docker-compose.local.yml up -d --build app
```

Data is never touched during upgrades — it lives in `./data/` which is a filesystem mount, not inside the container.

---

## Comparison: ngrok vs Cloudflare Tunnel

| | ngrok (Option 1) | Cloudflare Tunnel (Option 2) |
|---|---|---|
| Domain | Not needed | Required (~$10/yr) |
| URL | `*.ngrok-free.app` | `yourdomain.com` |
| URL stability | Permanent (with static domain) | Permanent |
| Setup | ~15 minutes | ~45 minutes |
| Auto-restart | Manual ngrok restart needed | Fully automatic |
| Cost | Free | ~$10/year |
| Best for | Getting started quickly | Long-term family use |
