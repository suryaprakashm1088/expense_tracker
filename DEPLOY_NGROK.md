# Setup Guide — Option 1: ngrok (No Domain Purchase)

Run the Expense Tracker on **your own computer** using ngrok to give the app a public HTTPS URL. No domain needed, nothing to buy. Twilio sends messages to your ngrok URL, which forwards them to your local app.

```
WhatsApp → Twilio → ngrok tunnel → your computer → Flask app → SQLite DB
```

---

## Before you start — choose your Twilio plan

| | **Sandbox (free)** | **Paid number (~$1/mo)** |
|---|---|---|
| Cost | Free | ~$1/month |
| Member join step | Each member sends a one-time `join <code>` message | No join code — members text directly |
| WhatsApp number | Shared Twilio test number | Your own dedicated number |
| Best for | Testing, small family trial | Ongoing family use |

You choose this in Part 2 below. The rest of the setup is identical.

---

## Part 1 — ngrok setup

### Step 1 — Create a free ngrok account

1. Go to [ngrok.com](https://ngrok.com) → **Sign up** (free)
2. After signing in, click **Your Authtoken** in the left sidebar
3. Copy the token — you'll need it in Step 3

### Step 2 — Install ngrok

**Mac:**
```bash
brew install ngrok
```

**Windows:** Download the `.zip` from [ngrok.com/download](https://ngrok.com/download), unzip it, and put `ngrok.exe` somewhere in your PATH (e.g. `C:\Windows\System32\`)

**Linux:**
```bash
curl -s https://ngrok-agent.s3.amazonaws.com/ngrok.asc | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
echo "deb https://ngrok-agent.s3.amazonaws.com buster main" | sudo tee /etc/apt/sources.list.d/ngrok.list
sudo apt update && sudo apt install ngrok
```

### Step 3 — Connect ngrok to your account

```bash
ngrok config add-authtoken YOUR_AUTHTOKEN_HERE
```

### Step 4 — Claim your free static domain ⭐ (strongly recommended)

Every free ngrok account gets **one free permanent subdomain**. Without it, your URL changes every restart and you have to update Twilio every time.

1. Go to [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains)
2. Click **New Domain** → ngrok assigns a permanent subdomain like `yourname.ngrok-free.app`
3. Note the full domain — you'll use it in Steps 9 and 11

> If you skip this: your URL looks like `https://abc123.ngrok-free.app` and changes on every restart. You'd have to update the Twilio webhook each time.

---

## Part 2 — Twilio setup

### Step 5 — Create a Twilio account

1. Go to [twilio.com](https://www.twilio.com) → **Sign up** (free)
2. Verify your email and phone number

### 2A — Sandbox setup (free, recommended for getting started)

1. In the Twilio Console → **Messaging → Try it out → Send a WhatsApp message**
2. Note down:
   - The **sandbox number** (e.g. `+1 415 523 8886`)
   - The **join code** (e.g. `join silver-flame`)
3. Your `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+14155238886`

> Members must send `join silver-flame` to the sandbox number once before they can use the bot. You'll share this with them in Part 5.

### 2B — Paid number setup (~$1/month)

1. In the Twilio Console → **Phone Numbers → Buy a Number**
2. Filter by **WhatsApp** capability → purchase a number
3. Go to **Messaging → Senders → WhatsApp Senders** → add your number
4. Twilio sends a WhatsApp verification message to that number — approve it
5. Your `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+<your-purchased-number>`

> ⚠️ WhatsApp Business API approval for a new number can take **1–3 business days**. Plan accordingly. The sandbox is available immediately.

---

## Part 3 — Configure the app

### Step 6 — Get the code

```bash
git clone <your-repo-url>
cd expense_tracker
```

Or download and unzip the project folder.

### Step 7 — Create your `.env` file

```bash
cp .env.example .env
```

Open `.env` in any text editor and fill in these values:

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

# REQUIRED — generate this value, do not leave as placeholder:
# Run this command and paste the output:
#   python3 -c "import secrets; print(secrets.token_hex(64))"
SECRET_KEY=paste-64-char-hex-here

# ── Your public URL ──────────────────────────────────────────────────────────
# Use your static ngrok domain from Step 4 (with https://)
# If you skipped Step 4, update this after Step 11 with your live ngrok URL
DASHBOARD_URL=https://yourname.ngrok-free.app

# ── Monitoring ───────────────────────────────────────────────────────────────
# Password for Grafana at http://localhost:3000 (set anything you like)
GRAFANA_ADMIN_PASSWORD=choose-a-strong-password

# ── Optional — enables AI daily summaries and receipt cloud fallback ─────────
# ANTHROPIC_API_KEY=sk-ant-api03-...
```

> 🔑 **SECRET_KEY is required.** Do not skip it or leave the placeholder. Generate it with:
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(64))"
> ```

### Step 8 — Install Docker Desktop

Download and install from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)

- **Mac:** Open Docker Desktop after installing. Wait until the whale icon in the menu bar stops animating.
- **Windows:** Enable WSL 2 integration if prompted.

---

## Part 4 — Start the app

### Step 9 — Build and start the container

```bash
docker compose -f docker-compose.local.yml up -d --build
```

First run takes 3–5 minutes (downloads Python packages). Subsequent starts are instant.

**Check it's running:**
```bash
docker ps
# Should show: expense_tracker   Up X seconds
```

**Watch the logs:**
```bash
docker logs expense_tracker -f
# Press Ctrl+C to stop following (app keeps running)
```

You should see gunicorn startup lines and no Python errors.

### Step 10 — First login

Open [http://localhost:5001](http://localhost:5001) in your browser.

You'll see a **green box with a one-time password (OTP)**. Log in with:
- **Username:** `admin`
- **Password:** *(the OTP shown in the green box)*

You are immediately prompted to set a permanent username and password. The OTP disappears after that.

---

## Part 5 — Connect Twilio

### Step 11 — Start ngrok

Open a **new terminal** (keep it open — ngrok must stay running):

**With your static domain (Step 4):**
```bash
ngrok http --domain=yourname.ngrok-free.app 5001
```

**Without a static domain:**
```bash
ngrok http 5001
# Copy the https://... URL that appears
```

### Step 12 — Set the Twilio webhook

**For Sandbox:**
1. Twilio Console → **Messaging → Try it out → Send a WhatsApp message → Sandbox settings**
2. Set **"When a message comes in"** to:
   ```
   https://yourname.ngrok-free.app/whatsapp
   ```
3. Method: **HTTP POST** → **Save**

**For Paid number:**
1. Twilio Console → **Phone Numbers → Manage → Active Numbers** → click your number
2. Under **Messaging** → **"A message comes in"**, paste:
   ```
   https://yourname.ngrok-free.app/whatsapp
   ```
3. Method: **HTTP POST** → **Save**

### Step 13 — Test the bot

**Sandbox:** First, send `join silver-flame` (your code) to `+1 415 523 8886`, then send `help`

**Paid number:** Just send `help` to your number

You should get a reply within a few seconds.

---

## Part 6 — Add family members

### Step 14 — Onboard members

**Via invite code (recommended):**
1. Dashboard → **Onboarding** → Generate a code for each member
2. Send them: *"Message +1 415 523 8886 with: `JOIN <code>`"*

**Via self-registration:**
1. Member messages the bot with anything
2. They get: *"Waiting for admin approval"*
3. You approve them on the **Members** page in the dashboard

**Sandbox extra step — share the join code with ALL members:**

> "To set up our family expense bot:
> 1. Save this number in WhatsApp: **+1 415 523 8886**
> 2. Send it this exact message: **join silver-flame**
> 3. Once you get a reply, you're in — message `help` to see commands"

This join step is a one-time thing per device. After that, members just message normally.

---

## Part 7 — Monitoring (optional)

### Step 15 — Start the monitoring stack

```bash
cd monitoring
docker compose -f docker-compose.monitoring.yml up -d
```

Open [http://localhost:3000](http://localhost:3000):
- Username: `admin`
- Password: your `GRAFANA_ADMIN_PASSWORD` from `.env`

The **Expense Tracker** dashboard loads automatically — shows HTTP metrics, expense counts, WhatsApp message rates, AI scan performance, and live container logs.

---

## Part 8 — AI receipt scanning (optional)

The app works without any AI. If you want receipt photos to be auto-scanned:

### LM Studio (best, free, runs locally on Mac)

1. Download [lmstudio.ai](https://lmstudio.ai)
2. Search for and download a **vision model** (e.g. `qwen2.5-vl-7b-instruct` — about 5 GB)
3. Go to **Local Server** tab → **Start Server**
4. That's it — the app is already configured to use it at `http://localhost:1234`

**Test it's working:**
```bash
curl http://localhost:1234/v1/models
```

### Ollama (fallback, free)

```bash
brew install ollama
ollama serve          # keep this running
ollama pull llava:7b  # download the vision model
```

### Claude Vision (cloud fallback)

Add to `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

The app tries LM Studio → Ollama → Claude Vision in that order. If none are available, receipt photos are accepted but not scanned.

---

## Daily operation

### Starting the app

```bash
# Terminal 1: app (starts automatically on boot if Docker Desktop is set to auto-start)
docker compose -f docker-compose.local.yml up -d

# Terminal 2: ngrok tunnel (must be running for WhatsApp to work)
ngrok http --domain=yourname.ngrok-free.app 5001

# If using LM Studio: open it → Local Server → Start Server
```

### Stopping

```bash
docker compose -f docker-compose.local.yml down
# Close the ngrok terminal
```

### View logs

```bash
docker logs expense_tracker -f
```

### Rebuild after code changes

```bash
docker compose -f docker-compose.local.yml up -d --build app
```

---

## ⚠️ Checklist — things people commonly miss

- [ ] `SECRET_KEY` generated (not left as placeholder text)
- [ ] `GRAFANA_ADMIN_PASSWORD` set to something real
- [ ] `DASHBOARD_URL` points to your ngrok URL (with `https://`)
- [ ] Twilio webhook URL ends in `/whatsapp` and uses `POST`
- [ ] ngrok terminal is open and running
- [ ] Sandbox members sent the `join <code>` message (one-time, per device)
- [ ] If using paid Twilio number — WhatsApp Business approval completed (1–3 days)
- [ ] If using LM Studio — Local Server is started inside the app
- [ ] `ANTHROPIC_API_KEY` set if you want AI daily summaries

---

## Troubleshooting

| Problem | Solution |
|---|---|
| App not starting | `docker logs expense_tracker` — look for Python import errors |
| WhatsApp bot not replying | Check ngrok is running; verify webhook URL in Twilio |
| Twilio says "Webhook Error" | ngrok may have restarted with a new URL — check and update Twilio |
| "Invalid username or password" | Use the OTP shown in the green box on the login page |
| "Not a member" reply from bot | Member isn't approved — check the Members page in the dashboard |
| Sandbox member can't use bot | They need to send `join <code>` to the Twilio number first |
| Receipt scan returns nothing | Check LM Studio Local Server is started; or set `ANTHROPIC_API_KEY` |
| Grafana shows no data | Check monitoring stack is running: `docker ps` |
| Port 5001 in use | `lsof -i :5001` (Mac) to find the conflicting process |

---

## Moving to a different computer

```bash
# On old computer — stop the app
docker compose -f docker-compose.local.yml down

# Copy the entire expense_tracker/ folder to the new computer
# (including ./data/expenses.db and .env)

# On new computer — install Docker Desktop, then:
docker compose -f docker-compose.local.yml up -d --build
```

Your data survives because it's in `./data/expenses.db` on your filesystem (not inside the container).
