#!/usr/bin/env bash
# One-shot server setup for a fresh Vultr Ubuntu 24.04 instance.
#
#   1. Point your domain's A record at this server's IP first (HTTPS needs it).
#   2. Copy the project here (git clone your repo into /opt/lifeline) and fill in backend/.env
#   3. sudo bash /opt/lifeline/deploy/setup_vultr.sh yourdomain.tech
#
# Re-run it any time to pull in code changes: it rebuilds and restarts.
set -euo pipefail

DOMAIN="${1:?Usage: sudo bash setup_vultr.sh yourdomain.tech}"
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Installing system packages"
apt-get update -y
apt-get install -y python3-venv python3-pip curl debian-keyring debian-archive-keyring apt-transport-https gnupg

if ! command -v node >/dev/null || [ "$(node -v | cut -d. -f1 | tr -d v)" -lt 20 ]; then
  echo "==> Installing Node.js 22"
  curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
  apt-get install -y nodejs
fi

if ! command -v caddy >/dev/null; then
  echo "==> Installing Caddy (automatic HTTPS)"
  # From Ubuntu's own repo: Caddy's cloudsmith repo started returning 402 Payment Required (Oct 2026)
  apt-get install -y caddy
fi

echo "==> Backend dependencies"
cd "$APP_DIR/backend"
[ -f .env ] || { echo "Missing backend/.env. Copy .env.example to .env and fill it in."; exit 1; }
python3 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q

echo "==> Building the dashboard"
cd "$APP_DIR/frontend"
npm install --no-audit --no-fund
npm run build

echo "==> Service"
sed "s#__APP_DIR__#$APP_DIR#g" "$APP_DIR/deploy/lifeline.service" > /etc/systemd/system/lifeline.service
systemctl daemon-reload
systemctl enable lifeline
systemctl restart lifeline

echo "==> HTTPS for $DOMAIN"
sed "s#__DOMAIN__#$DOMAIN#g" "$APP_DIR/deploy/Caddyfile" > /etc/caddy/Caddyfile
systemctl restart caddy

if command -v ufw >/dev/null && ufw status | grep -q active; then
  ufw allow 80/tcp && ufw allow 443/tcp
fi

sleep 3
echo
echo "Done. Check: https://$DOMAIN/api/health"
echo "Logs:  journalctl -u lifeline -f"
echo "Now update the ElevenLabs tool URLs and post-call webhook to https://$DOMAIN"
