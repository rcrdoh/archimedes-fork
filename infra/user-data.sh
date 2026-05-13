#!/bin/bash
set -euxo pipefail

# ---------------------------------------------------------------
# Archimedes EC2 bootstrap — runs once on first boot via cloud-init
# Installs Docker, clones repo, starts services
# ---------------------------------------------------------------

export DEBIAN_FRONTEND=noninteractive

# System updates
apt-get update -y
apt-get upgrade -y

# Install Docker CE
apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update -y
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Enable Docker, add ubuntu user to docker group
systemctl enable docker
systemctl start docker
usermod -aG docker ubuntu

# Install git (usually pre-installed, but be safe)
apt-get install -y git

# Create app directory
mkdir -p /opt/archimedes
chown ubuntu:ubuntu /opt/archimedes

# Clone the repo
su - ubuntu -c "git clone ${repo_url} /opt/archimedes"

# Create a placeholder .env on the server (team will populate secrets later)
cat > /opt/archimedes/.env <<'ENVEOF'
# Archimedes production environment — populated by the team
# Do NOT commit this file. See .env.example for the template.
POSTGRES_USER=archimedes
POSTGRES_PASSWORD=archimedes-hackathon-2026
POSTGRES_DB=archimedes
REDIS_URL=redis://redis:6379/0
DATABASE_URL=postgresql://archimedes:archimedes-hackathon-2026@postgres:5432/archimedes
ENVEOF
chown ubuntu:ubuntu /opt/archimedes/.env

# Start services (if docker-compose.yml exists)
if [ -f /opt/archimedes/docker-compose.yml ]; then
  su - ubuntu -c "cd /opt/archimedes && docker compose up --build -d"
fi

# Signal that cloud-init is done
echo "archimedes-bootstrap-complete" > /tmp/bootstrap-done
