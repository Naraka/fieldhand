#!/usr/bin/env bash
# One-command install on a fresh Ubuntu server (tested target: Oracle Cloud Always Free, ARM).
#
#   curl -fsSL https://raw.githubusercontent.com/Naraka/fieldhand/main/deploy/install.sh \
#     | sudo FIELDHAND_DOMAIN=fieldhand.example.com bash
set -euo pipefail

: "${FIELDHAND_DOMAIN:?set FIELDHAND_DOMAIN to the domain that points to this server}"
REPO="${FIELDHAND_REPO:-https://github.com/Naraka/fieldhand}"

apt-get update
apt-get install -y git curl debian-keyring debian-archive-keyring apt-transport-https

# Caddy from its official repository.
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  > /etc/apt/sources.list.d/caddy-stable.list
apt-get update
apt-get install -y caddy

# Service user, code and data.
id fieldhand >/dev/null 2>&1 || useradd --system --home /var/lib/fieldhand --shell /usr/sbin/nologin fieldhand
install -d -m 700 -o fieldhand -g fieldhand /var/lib/fieldhand
if [ -d /opt/fieldhand/.git ]; then
  git -C /opt/fieldhand pull --ff-only
else
  git clone "$REPO" /opt/fieldhand
fi
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
(cd /opt/fieldhand && uv sync --no-dev --frozen)

if [ ! -f /etc/fieldhand.env ]; then
  install -m 600 /dev/null /etc/fieldhand.env
  printf 'FIELDHAND_GITHUB_CLIENT_ID=\nFIELDHAND_GITHUB_CLIENT_SECRET=\nFIELDHAND_BACKUP_URL=\n' \
    > /etc/fieldhand.env
fi
install -m 644 /opt/fieldhand/deploy/fieldhand.service /etc/systemd/system/fieldhand.service
install -m 644 /opt/fieldhand/deploy/fieldhand-backup.service /etc/systemd/system/
install -m 644 /opt/fieldhand/deploy/fieldhand-backup.timer /etc/systemd/system/
install -m 644 /opt/fieldhand/deploy/Caddyfile /etc/caddy/Caddyfile
mkdir -p /etc/systemd/system/caddy.service.d
printf '[Service]\nEnvironment=FIELDHAND_DOMAIN=%s\n' "$FIELDHAND_DOMAIN" \
  > /etc/systemd/system/caddy.service.d/fieldhand.conf

# Oracle's Ubuntu images block everything but SSH in iptables.
if command -v netfilter-persistent >/dev/null; then
  for port in 80 443; do
    iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 5 -p tcp --dport "$port" -j ACCEPT
  done
  netfilter-persistent save
fi

systemctl daemon-reload
systemctl enable --now fieldhand
systemctl enable --now fieldhand-backup.timer
systemctl restart caddy
echo "Fieldhand is running at https://$FIELDHAND_DOMAIN (API docs at /docs)."
echo "Remember to open ports 80 and 443 in the cloud firewall (Oracle: VCN security list)."
grep -q 'CLIENT_ID=.' /etc/fieldhand.env \
  || echo "Registration is open until you set up GitHub sign-in in /etc/fieldhand.env (see deploy/README.md)."
