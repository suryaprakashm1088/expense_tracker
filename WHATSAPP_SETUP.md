# WhatsApp Bot Setup Guide

This guide connects your Expense Tracker to WhatsApp using Twilio (free) and ngrok (free).

---

## What You Need (all free)
- Twilio account → https://twilio.com
- ngrok account  → https://ngrok.com

---

## STEP 1 — Install dependencies

```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
pip3 install flask twilio
```

---

## STEP 2 — Install & start ngrok (gives your app a public URL)

```bash
# Install via Homebrew
brew install ngrok

# Sign up at https://ngrok.com → copy your authtoken → run:
ngrok config add-authtoken YOUR_TOKEN_HERE

# Start tunnel (keep this running in a separate Terminal tab)
ngrok http 5001
```

You'll see output like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:5001
```
**Copy that https URL** — you'll need it in Step 4.

---

## STEP 3 — Set up Twilio WhatsApp Sandbox

1. Go to https://twilio.com and create a free account
2. In the Twilio Console, go to:
   **Messaging → Try it out → Send a WhatsApp message**
3. You'll see a **Sandbox number** like `+1 415 523 8886`
   and a join code like `join silver-flame`
4. **Share with your WhatsApp group:**
   > "Save this number: +1 415 523 8886
   > Send it this message to join our expense tracker:
   > join silver-flame"
5. Each member must send that join message **once** to activate

---

## STEP 4 — Connect Twilio to your app

In the Twilio Sandbox settings page, find:

**"When a message comes in" → Webhook URL**

Set it to:
```
https://abc123.ngrok-free.app/whatsapp
```
(replace abc123 with your actual ngrok URL from Step 2)

Set the method to **HTTP POST** → click **Save**.

---

## STEP 5 — Start the app

Open **two Terminal tabs**:

**Tab 1 — ngrok:**
```bash
ngrok http 5001
```

**Tab 2 — Flask app:**
```bash
cd "/Users/suryaprakashm/Documents/Claude/Projects/Expence Manager/expense_tracker"
python3 app.py
```

---

## STEP 6 — Approve members

1. Ask group members to message the Twilio number
2. They'll get a "waiting for approval" reply automatically
3. Go to http://127.0.0.1:5001/members in your browser
4. Click **Approve** next to each member
5. Once approved, they can log expenses immediately!

---

## How Members Log Expenses

Send these messages to the Twilio WhatsApp number:

| Message | What it does |
|---|---|
| `add food 500 lunch` | Adds $500 under Food & Groceries |
| `add 1200 bills electricity` | Adds $1200 under Bills |
| `uber 250 office trip` | Adds $250 under Transport |
| `netflix 649` | Adds $649 under Entertainment |
| `summary` | Monthly category breakdown |
| `total` | This month's total spend |
| `today` | Today's expenses |
| `recent` | Last 5 expenses |
| `help` | All commands |

---

## Security Summary

| Layer | Protection |
|---|---|
| Twilio sandbox join code | Only people with the code can message the bot |
| Admin approval | You approve each member manually |
| Revoke anytime | Remove or suspend any member from the Members page |
| Data stored locally | All data stays on your Mac, never in the cloud |

---

## Troubleshooting

**Bot not responding?**
- Make sure both ngrok and `python3 app.py` are running
- Check the webhook URL in Twilio matches your current ngrok URL
- ngrok URL changes every time you restart it — update Twilio if needed

**Member getting "not approved" message?**
- Go to http://127.0.0.1:5001/members and click Approve

**ngrok URL keeps changing?**
- Sign up for ngrok paid plan ($0/mo free tier gives a stable domain)
- Or use ngrok's static domain (free): `ngrok http --domain=yourname.ngrok-free.app 5001`
