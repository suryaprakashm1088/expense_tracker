# Local AI Setup Guide

> ✅ **Works on Mac and Windows.** Platform-specific steps are marked clearly below.

The app uses a **three-tier AI fallback** for receipt scanning. It tries each engine in order and uses the first one that's available:

| Priority | Engine | Type | Cost | Receipt Scanning | AI Summaries |
|---|---|---|---|---|---|
| 1st | **LM Studio** | Local (GPU) | Free | ✅ Yes | ❌ No |
| 2nd | **Ollama** | Local (GPU) | Free | ✅ Yes | ❌ No |
| 3rd | **Claude Vision API** | Cloud | Pay-per-use | ✅ Yes | ✅ Yes (Haiku) |

**All AI is optional.** The app works fine without any of these — receipt photos are accepted but not auto-scanned, and daily summaries are skipped.

---

## Option A — LM Studio (recommended primary engine)

LM Studio hosts any vision model locally and exposes an OpenAI-compatible API on port 1234.

### Step 1 — Download LM Studio

Go to [lmstudio.ai](https://lmstudio.ai) → download and install the app for your OS.

- **🍎 Mac:** `.dmg` installer — drag to Applications
- **🪟 Windows:** `.exe` installer — run and follow the prompts

### Step 2 — Download a vision model

Inside LM Studio:
1. Click the **Search** tab (magnifying glass icon)
2. Search for a vision model. Recommended options:

| Model | Size | Quality | Best for |
|---|---|---|---|
| `qwen2.5-vl-7b-instruct` | ~5 GB | Excellent | Mac M-series, Windows with GPU |
| `llava-1.5-7b` | ~4 GB | Good | Mac M-series, Windows with GPU |
| `qwen2.5-vl-3b-instruct` | ~2 GB | Decent | CPU-only or low RAM machines |

3. Click **Download** on your chosen model

> **🪟 Windows — no GPU?** Use `qwen2.5-vl-3b-instruct` (2 GB). It runs on CPU — slower but works fine for occasional receipt scanning.

### Step 3 — Start the Local Server

1. Click the **Local Server** tab (≡ icon in the left sidebar)
2. Select your downloaded model from the dropdown
3. Click **Start Server**

The server runs on `http://localhost:1234`. The Docker container reaches it at `http://host.docker.internal:1234` — already configured in `docker-compose.local.yml`.

**Verify it's running:**
```bash
curl http://localhost:1234/v1/models
# Returns JSON listing your loaded model
```

### Step 4 — Keep it running

LM Studio must be running whenever you want receipt scanning to work. It does not auto-start — open the app and start the server manually each time.

**🍎 Mac — auto-start tip:**
> Add LM Studio to Login Items: **System Settings → General → Login Items → +**. You still need to start the Local Server inside the app after it opens.

**🪟 Windows — auto-start tip:**
> Pin LM Studio to your Taskbar or Startup folder (`Win+R` → `shell:startup`) so it opens on login. You still need to start the Local Server inside the app.

---

## Option B — Ollama (fallback engine)

Ollama hosts vision models locally as a background service.

### Install

**🍎 Mac:**
```bash
brew install ollama
```
> Don't have Homebrew? Install it: `/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"`

**🪟 Windows:**
1. Download the installer from [ollama.com](https://ollama.com)
2. Run the `.exe` — Ollama installs as a **background Windows service** that starts automatically on login (no manual start needed)

### Pull a vision model

```bash
ollama pull llava:7b        # ~4 GB — good balance of speed and accuracy
# OR for higher quality (needs more RAM):
ollama pull llava:13b       # ~8 GB
```

This command is the same on Mac and Windows — run it in any terminal.

### Start Ollama

**🍎 Mac:**
```bash
# Run in a terminal (stops when terminal closes)
ollama serve

# OR run as a background service (starts automatically on login)
brew services start ollama
```

**🪟 Windows:**
Ollama starts automatically as a Windows service after installation. If it's not running:
1. Search **"Ollama"** in the Start Menu and open it
2. Or restart the service: open **Services** (`Win+R` → `services.msc`) → find **Ollama** → Start

### Verify

```bash
curl http://localhost:11434/api/tags
# Returns JSON listing your available models
```

---

## Option C — Claude Vision API (cloud fallback)

If neither LM Studio nor Ollama is available, the app falls back to Anthropic's Claude Vision API. This also powers the **AI daily summary** feature. Works identically on Mac and Windows.

### Get an API key

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an account and add a payment method
3. Go to **API Keys** → **Create Key**
4. Copy the key (starts with `sk-ant-api03-`)

### Add to your `.env`

```bash
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
```

Restart the app after changing `.env`:
```bash
docker compose -f docker-compose.local.yml up -d --build app
```

### Cost

- Receipt scanning uses Claude Vision (claude-3-haiku) — approximately $0.001–0.003 per photo
- Daily summary uses Claude Haiku — approximately $0.001 per family per day
- Very low cost for personal use

---

## How to check which AI is active

The app automatically uses whichever tier is available. To see which one is currently being used:

```bash
# Check app logs during a receipt scan
docker logs expense_tracker -f

# Look for lines like:
# "Scanning receipt with LM Studio (qwen2.5-vl-7b-instruct)"
# "LM Studio unavailable, trying Ollama"
# "Using Claude Vision API (fallback)"
```

Or check the AI status endpoint:
```bash
curl http://localhost:5001/api/ai-status
```

---

## Environment variables reference

These are already configured in `docker-compose.local.yml`. Override in `.env` only if you want to change models:

```bash
# LM Studio (primary)
LM_STUDIO_URL=http://host.docker.internal:1234/v1
LM_STUDIO_VISION_MODEL=qwen2.5-vl-7b-instruct   # match your loaded model name

# Ollama (fallback)
OLLAMA_URL=http://host.docker.internal:11434
OLLAMA_VISION=llava:7b

# Claude (cloud fallback + summaries)
ANTHROPIC_API_KEY=sk-ant-api03-...
```

---

## Troubleshooting

| Problem | Solution |
|---|---|
| "LM Studio unavailable" in logs | Open LM Studio → Local Server → Start Server |
| LM Studio running but scan fails | Check the loaded model name matches `LM_STUDIO_VISION_MODEL` in compose file |
| "Ollama unreachable" (Mac) | Run `ollama serve` or `brew services start ollama` |
| "Ollama unreachable" (Windows) | Open Ollama from Start Menu or restart via Services (`services.msc`) |
| Ollama: model not found | Run `ollama pull llava:7b` |
| All local AI unavailable | Add `ANTHROPIC_API_KEY` to `.env` for cloud fallback |
| Slow on first receipt | Normal — model loads into GPU RAM on first call; fast after that |
| Out of memory (Mac) | Switch to `qwen2.5-vl-3b-instruct` (2 GB) |
| Out of memory (Windows) | Switch to `qwen2.5-vl-3b-instruct` (2 GB) or enable GPU in LM Studio settings |

---

## Architecture diagram

```
Your Computer
│
├── 🍎 Mac: Apple Silicon Metal GPU
│   🪟 Windows: NVIDIA/AMD GPU (or CPU fallback)
│
├── LM Studio  →  port 1234   (primary vision)
│   └── qwen2.5-vl-7b or any vision model
│
├── Ollama     →  port 11434  (fallback vision)
│   └── llava:7b
│
└── Docker Desktop
    └── expense_tracker container
        └── Flask app
            │
            ├── Receipt scan: tries LM Studio → Ollama → Claude Vision API
            └── AI summary:   uses Claude Haiku (requires ANTHROPIC_API_KEY)
```
