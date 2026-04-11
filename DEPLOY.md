# AWS EC2 Deployment Guide — Expense Tracker

## Architecture

```
Internet
   │
   ▼
Cloudflare (DNS + DDoS protection)
   │
   ▼
AWS EC2  t4g.small  (Ubuntu 24.04)
   │
   ├── Nginx  :80/:443   (reverse proxy + SSL termination)
   │      │
   │      └── Flask App  :5001  (gunicorn, 2 workers)
   │                │
   │                └── SQLite  ./data/expenses.db  (host-mounted volume)
   │
   └── Certbot  (Let's Encrypt SSL, auto-renews monthly)
```

---

## Prerequisites

- AWS account with EC2 access
- A domain name (DNS managed in Cloudflare)
- GitHub repo with this code
- Local machine with SSH client and git

---

## Step 1 — Launch EC2 Instance

1. Open **AWS Console → EC2 → Launch Instance**
2. Configure:

   | Setting | Value |
   |---|---|
   | Name | `expense-tracker` |
   | AMI | Ubuntu Server 24.04 LTS |
   | Instance type | `t4g.small` (ARM, 2 vCPU, 2GB RAM) |
   | Key pair | Create new → download `.pem` file |
   | Storage | 20 GB gp3 |

3. **Security Group — open these ports:**

   | Type | Port | Source |
   |---|---|---|
   | SSH | 22 | My IP (your home IP only) |
   | HTTP | 80 | 0.0.0.0/0 |
   | HTTPS | 443 | 0.0.0.0/0 |

4. Click **Launch Instance**

---

## Step 2 — Allocate & Associate Elastic IP

1. **EC2 → Elastic IPs → Allocate Elastic IP address** → Allocate
2. Select the new IP → **Actions → Associate Elastic IP address**
3. Choose your `expense-tracker` instance → Associate
4. Note your **Elastic IP** — needed for DNS

---

## Step 3 — Connect to Your Server

```bash
chmod 400 ~/Downloads/your-key.pem
ssh -i ~/Downloads/your-key.pem ubuntu@YOUR_ELASTIC_IP
```

---

## Step 4 — Install Dependencies on EC2

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker ubuntu
newgrp docker

# Install Docker Compose plugin
sudo apt install docker-compose-plugin -y

# Install Certbot and sqlite3
sudo apt install certbot sqlite3 -y

# Verify
docker --version && docker compose version && certbot --version
```

---

## Step 5 — Clone Your Repository

```bash
cd /home/ubuntu
git clone https://github.com/YOUR_USERNAME/expense_tracker.git expense_tracker
cd expense_tracker
```

---

## Step 6 — Configure Environment Variables

```bash
cp .env.example .env
nano .env
```

Fill in every value:

```env
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=your_real_auth_token
TWILIO_WHATSAPP_NUMBER=whatsapp:+14155238886
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxx
FLASK_ENV=production
SECRET_KEY=<generate below>
DASHBOARD_URL=https://yourdomain.com
DB_PATH=/data/expenses.db
```

Generate SECRET_KEY:
```bash
python3 -c "import secrets; print(secrets.token_hex(64))"
```

---

## Step 7 — Create Data Directory

```bash
mkdir -p /home/ubuntu/expense_tracker/data
```

---

## Step 8 — Configure Cloudflare DNS

1. Log in to **https://dash.cloudflare.com** → your domain → **DNS → Records**
2. Add records:

   | Type | Name | Content | Proxy |
   |---|---|---|---|
   | A | `@` | `YOUR_ELASTIC_IP` | ✅ Proxied |
   | A | `www` | `YOUR_ELASTIC_IP` | ✅ Proxied |

3. **SSL/TLS → Overview** → Mode: **Full (strict)**
4. **SSL/TLS → Edge Certificates** → **Always Use HTTPS**: ON

---

## Step 9 — Get SSL Certificate

Temporarily grey-cloud your domain in Cloudflare (disable proxy), then:

```bash
sudo certbot certonly --standalone \
  -d yourdomain.com \
  -d www.yourdomain.com \
  --email your@email.com \
  --agree-tos \
  --non-interactive

# Verify
sudo ls /etc/letsencrypt/live/yourdomain.com/
```

Re-enable the Cloudflare proxy (orange cloud) after this step.

---

## Step 10 — Update nginx.conf with Your Domain

```bash
nano nginx/nginx.conf
# Replace ALL occurrences of 'yourdomain.com' with your actual domain
# (3 places: server_name x2 and ssl_certificate paths)
```

---

## Step 11 — First Deploy

```bash
cd /home/ubuntu/expense_tracker
chmod +x scripts/deploy.sh scripts/backup.sh scripts/health_check.sh

docker compose up -d --build
docker compose logs -f app   # watch startup
```

---

## Step 12 — Verify Everything Works

```bash
curl https://yourdomain.com/health
# → {"status": "ok", "service": "expense-tracker"}

docker compose ps
# Both containers show 'running'
```

Open **https://yourdomain.com** → you should see the login page.
Default credentials: `admin` / `Admin@123` (you'll be forced to change these on first login).

---

## Step 13 — Update Twilio Webhook

1. Go to **https://console.twilio.com**
2. **Messaging → Settings → WhatsApp sandbox settings**
3. Set webhook URL to:
   ```
   https://yourdomain.com/whatsapp
   ```
4. Method: **HTTP POST** → Save

---

## Step 14 — Set Up Cron Jobs

```bash
crontab -e
```

Add:

```cron
# Daily database backup at 2:00 AM
0 2 * * * /home/ubuntu/expense_tracker/scripts/backup.sh >> /var/log/expense_backup.log 2>&1

# Health check every 5 minutes — auto-restarts if app crashes
*/5 * * * * /home/ubuntu/expense_tracker/scripts/health_check.sh >> /var/log/expense_health.log 2>&1

# Auto-renew SSL on 1st of each month
0 0 1 * * certbot renew --quiet && docker compose -f /home/ubuntu/expense_tracker/docker-compose.yml restart nginx
```

---

## Useful Commands

```bash
docker compose logs -f app           # live app logs
docker compose logs -f nginx         # live nginx logs
docker compose restart app           # restart app only
./scripts/deploy.sh                  # deploy new version
./scripts/backup.sh                  # manual backup
curl http://localhost:5001/health    # internal health check
docker compose exec app bash         # shell inside container
docker compose down                  # stop everything
docker compose up -d --build         # rebuild from scratch
```

---

## Cost Breakdown

| Service | Cost |
|---|---|
| EC2 t4g.small | ~$12/month |
| EBS 20GB gp3 | ~$1.60/month |
| Elastic IP (attached) | Free |
| Cloudflare DNS + proxy | Free |
| Let's Encrypt SSL | Free |
| **Total** | **~$14/month** |

> 💡 Use `t4g.nano` (~$5/month) for low traffic — sufficient for a family tracker.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| 502 Bad Gateway | `docker compose restart app` then check `docker compose logs app` |
| SSL error 526 | Ensure certbot cert exists; set Cloudflare mode to Full (strict) |
| DB permission error | `sudo chown -R 1000:1000 data/` then restart app |
| WhatsApp not responding | Check Twilio webhook URL; `curl -X POST https://yourdomain.com/whatsapp` |
| App crashes on start | Check `.env` has all required values; check logs |
