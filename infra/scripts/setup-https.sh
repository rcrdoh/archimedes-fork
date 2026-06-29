#!/usr/bin/env bash
# DEPRECATED / LEGACY — retained for reference only (T3.7).
# Production TLS now terminates UPSTREAM at CloudFront + the ALB (ACM certs); the
# EC2 serves plain HTTP on :8080 and does NOT run certbot for the live TLS path
# (nginx/nginx.conf keeps an ACME `/.well-known/acme-challenge/` passthrough only
# for optional, out-of-band renewals — it is not used on the current CloudFront path).
# This in-instance Let's Encrypt flow is from the pre-CloudFront era on the now-
# decommissioned archimedes-arc.app domain and is NOT part of the current
# architecture. Do not run it against prod.
# Usage (historical): ssh ubuntu@<host> 'bash -s' < infra/scripts/setup-https.sh
set -euo pipefail

# Safety guard: this legacy script provisions Let's Encrypt against a HARDCODED
# prod domain/email below. Refuse to run unless an operator explicitly opts in,
# so a stray `bash -s` can never fire it by accident.
if [[ "${ALLOW_LEGACY_HTTPS_SETUP:-}" != "1" ]]; then
  echo "DEPRECATED: in-instance certbot is not the live TLS path (CloudFront/ACM is)." >&2
  echo "Refusing to run. Set ALLOW_LEGACY_HTTPS_SETUP=1 to override intentionally." >&2
  exit 1
fi

DOMAIN="archimedes-arc.com"
EMAIL="dbrowne.up@gmail.com"
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
