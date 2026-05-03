# Setup Guide — Option 1: ngrok (No Domain Purchase)

Run the Expense Tracker on **your own computer** using ngrok to give the app a public HTTPS URL. No domain needed, nothing to buy. Twilio sends messages to your ngrok URL, which forwards them to your local app.

```
WhatsApp → Twilio → ngrok tunnel → your computer → Flask app → SQLite DB
```

> ✅ **Works on Mac and Windows.** Platform-specific steps are marked clearly below.

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

**🍎 Mac:**
```bash
brew install ngrok
```
> Don't have Homebrew? Install it first: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

**🪟 Windows:**
1. Download the `.zip` from [ngrok.com/download](https://ngrok.com/download)
2. Unzip it — you get a single `ngrok.exe` file
3. Move `ngrok.exe` to `C:\Windows\System32\` so it's available from any terminal
4. Open **Command Prompt** or **PowerShell** to run ngrok commands

**🐧 Linux:**
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

> If you skip this: your URL changes on every restart and you'd have to update the Twilio webhook each time.

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

> Members must send `join silver-flame` to the sandbox number once before they can use the bot.

### 2B — Paid number setup (~$1/month)

1. In the Twilio Console → **Phone Numbers → Buy a Number**
2. Filter by **WhatsApp** capability → purchase a number
3. Go to **Messaging → Senders → WhatsApp Senders** → add your number
4. Twilio sends a WhatsApp verification message to that number — approve it
5. Your `TWILIO_WHATSAPP_NUMBER` = `whatsapp:+<your-purchased-number>`

> ⚠️ WhatsApp Business API approval for a new number can take **1–3 business days**. The sandbox is available immediately.

---

## Part 3 — Configure the app

### Step 6 — Get the code

```bash
git clone <your-repo-url>
cd expense_tracker
```

Or download and unzip the project folder.

### Step 7 — Create your `.env` file

**🍎 Mac / 🐧 Linux:**
```bash
cp .env.example .env
```

**🪟 Windows (Command Prompt):**
```cmd
copy .env.example .env
```

**🪟 Windows (PowerShell):**
```powershell
Copy-Item .env.example .env
```

Open `.env` in any text editor and fill in:

```bash
# ── Twilio ──────────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Sandbox:  whatsapp:+14155238886
# Paid:     whatsapp:+<your-purchased-number>
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886

# ── Flask ────────────────────────────────────────────────────────────────────
FLASK_ENV=production

# REQUIRED — generate and paste the output below:
SECRET_KEY=paste-64-char-hex-here

# ── Your public URL ───────────────────────────────────────────────────────────
DASHBOARD_URL=https://yourname.ngrok-free.app

# ── Monitoring ───────────────────────────────────────────────────────────────
GRAFANA_ADMIN_PASSWORD=choose-a-strong-password

# ── Optional — AI summaries + receipt cloud fallback ─────────────────────────
# ANTHROPIC_API_KEY=sk-ant-api03-...
```

> 🔑 **SECRET_KEY is required.** Generate it:
>
> **🍎 Mac / 🐧 Linux:**
> ```bash
> python3 -c "import secrets; print(secrets.token_hex(64))"
> ```
> **🪟 Windows (PowerShell):**
> ```powershell
> python -c "import secrets; print(secrets.token_hex(64))"
> ```

### Step 8 — Install Docker Desktop

Download from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop)

**🍎 Mac:**
- Open Docker Desktop after installing
- Wait until the whale icon in the menu bar stops animating
- No extra configuration needed

**🪟 Windows:**
- Run the installer — it will prompt you to enable **WSL 2** (Windows Subsystem for Linux)
- Click **Yes / Enable** when prompted — this is required for Docker to work
- Restart your computer if asked
- Open Docker Desktop and wait for the whale icon in the taskbar to stop animating

---

## Part 4 — Start the app

### Step 9 — Build and start the container

```bash
docker compose -f docker-compose.local.yml up -d --build
```

> **🪟 Windows note:** Run this in **PowerShell** or **Command Prompt** (not WSL terminal) from the `expense_tracker` folder.

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
# Copy the https://... URL that appears — update DASHBOARD_URL in .env and Twilio webhook
```

> **🪟 Windows:** Run this in a separate **Command Prompt** or **PowerShell** window. Keep it open.

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
2. Under **Messaging → "A message comes in"**, paste:
   ```
   https://yourname.ngrok-free.app/whatsapp
   ```
3. Method: **HTTP POST** → **Save**

### Step 13 — Test the bot

**Sandbox:** First send `join silver-flame` (your code) to `+1 415 523 8886`, then send `help`

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

The app works without any AI. If you want receipt photos to be auto-scanned, the app tries these in order: **LM Studio → Ollama → Claude Vision API**

### LM Studio (best — free, local)

LM Studio runs AI locally on your GPU — no API costs.

**🍎 Mac (Apple Silicon — Metal GPU):**
1. Download [lmstudio.ai](https://lmstudio.ai) and install the Mac app
2. Open LM Studio → **Search** tab → search `qwen2.5-vl-7b-instruct` → Download (~5 GB)
3. Go to **Local Server** tab → select the model → **Start Server**
4. The app is pre-configured — no `.env` changes needed

> Apple Silicon (M1/M2/M3/M4) uses Metal GPU acceleration — fast and efficient.

**🪟 Windows:**
1. Download [lmstudio.ai](https://lmstudio.ai) and install the Windows app
2. Open LM Studio → **Search** tab → search `qwen2.5-vl-7b-instruct` → Download (~5 GB)
3. Go to **Local Server** tab → select the model → **Start Server**
4. The app is pre-configured — no `.env` changes needed

> Windows uses your **NVIDIA or AMD GPU** if available (CUDA/ROCm). Falls back to CPU if no GPU — slower but still works. For CPU-only machines try `qwen2.5-vl-3b-instruct` (2 GB, faster).

**Test it's working:**
```bash
curl http://localhost:1234/v1/models
```

### Ollama (fallback — free, local)

**🍎 Mac:**
```bash
brew install ollama
ollama serve          # keep this running in a terminal
ollama pull llava:7b  # download the vision model (~4 GB)
```

**🪟 Windows:**
1. Download the installer from [ollama.com](https://ollama.com) and install it
2. Ollama runs as a background service automatically — no need to start it manually
3. Open **Command Prompt** or **PowerShell** and run:
```cmd
ollama pull llava:7b
```

**Verify Ollama is running:**
```bash
curl http://localhost:11434/api/tags
```

### Claude Vision (cloud fallback)

Works identically on Mac and Windows. Add to `.env`:
```bash
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## Daily operation

### Starting the app

**🍎 Mac:**
```bash
# Terminal 1 — app
docker compose -f docker-compose.local.yml up -d

# Terminal 2 — ngrok tunnel (must stay open)
ngrok http --domain=yourname.ngrok-free.app 5001

# If using LM Studio: open it → Local Server → Start Server
```

**🪟 Windows:**
```powershell
# PowerShell window 1 — app
docker compose -f docker-compose.local.yml up -d

# PowerShell window 2 — ngrok tunnel (must stay open)
ngrok http --domain=yourname.ngrok-free.app 5001

# If using LM Studio: open it → Local Server → Start Server
```

### Stopping

```bash
docker compose -f docker-compose.local.yml down
# Close the ngrok terminal/window
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
- [ ] **Windows only:** WSL 2 enabled and Docker Desktop showing "Engine running"

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
| Port 5001 in use (Mac) | `lsof -i :5001` to find the conflicting process |
| Port 5001 in use (Windows) | `netstat -ano \| findstr :5001` then `taskkill /PID <pid> /F` |
| Docker not starting (Windows) | Make sure WSL 2 is enabled and Docker Desktop shows "Engine running" |
| `docker` command not found (Windows) | Docker Desktop not running — open it from Start Menu first |

---

## Moving to a different computer

**🍎 Mac → Mac / 🪟 Windows → Windows:**
```bash
# Old computer — stop the app
docker compose -f docker-compose.local.yml down

# Copy the entire expense_tracker/ folder to the new computer
# (including ./data/expenses.db and .env)

# New computer — install Docker Desktop, then:
docker compose -f docker-compose.local.yml up -d --build
```

**🍎 Mac → 🪟 Windows (or vice versa):**
Same steps above. The `./data/expenses.db` file is portable — SQLite works identically on both platforms. Your ngrok static domain and Twilio webhook URL stay the same.
