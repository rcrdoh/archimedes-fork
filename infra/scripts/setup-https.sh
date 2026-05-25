#!/usr/bin/env bash
# Idempotent HTTPS setup for archimedes-arc.app on EC2
# Usage: ssh ubuntu@<host> 'bash -s' < infra/scripts/setup-https.sh
set -euo pipefail

DOMAIN="archimedes-arc.app"
EMAIL="chuan@gyld.fi"
COMPOSE_DIR="/opt/archimedes"

echo "=== [1/4] Install certbot ==="
if ! command -v certbot &>/dev/null; then
    sudo apt-get update -qq && sudo apt-get install -y -qq certbot
fi
echo "certbot $(certbot --version 2>&1)"

echo "=== [2/4] Obtain certificate (standalone mode) ==="
if [ -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
    echo "Certificate already exists — skipping issuance"
else
    # Stop nginx container to free port 80 for standalone challenge
    echo "Stopping nginx container..."
    cd "$COMPOSE_DIR" && docker compose stop nginx 2>/dev/null || true

    sudo certbot certonly --standalone \
        -d "$DOMAIN" \
        --email "$EMAIL" \
        --agree-tos \
        --non-interactive \
        --no-eff-email

    echo "Certificate obtained"
fi

echo "=== [3/4] Fix permissions for Docker mount ==="
# Let the nginx container (non-root) read the cert files
sudo chmod 0755 /etc/letsencrypt/live /etc/letsencrypt/archive
sudo chmod 0644 /etc/letsencrypt/archive/${DOMAIN}/*.pem 2>/dev/null || true

echo "=== [4/4] Restart stack with HTTPS ==="
cd "$COMPOSE_DIR"
git pull origin main 2>/dev/null || true
docker compose up -d --build nginx
echo ""
echo "=== Verify ==="
sleep 3
curl -sI "https://${DOMAIN}/" 2>/dev/null | head -5 || echo "(DNS may still be propagating)"
echo ""
echo "=== Auto-renewal cron ==="
# certbot on Ubuntu 24.04 ships with a systemd timer; verify it's active
if systemctl is-active --quiet certbot.timer 2>/dev/null; then
    echo "certbot.timer is active ✓"
else
    # Fallback: add cron entry
    (crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet --deploy-hook 'cd ${COMPOSE_DIR} && docker compose restart nginx'") | sort -u | crontab -
    echo "Added certbot renewal cron"
fi

echo ""
echo "Done. HTTPS should be live at https://${DOMAIN}/"
