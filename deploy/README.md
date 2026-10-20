# Deploy

Fieldhand runs as one process with a SQLite file, so a small free VM is enough.
The target is **Oracle Cloud Always Free** (Ampere ARM VM, Ubuntu).

1. Create the VM and point a domain (or a free subdomain) to its public IP.
2. In the VCN security list, allow ingress TCP 80 and 443.
3. On the VM:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/Naraka/fieldhand/main/deploy/install.sh \
     | sudo FIELDHAND_DOMAIN=fieldhand.example.com bash
   ```

The script installs Caddy (HTTPS), uv and the server as a systemd service.
Run it again to update to the latest version.

## GitHub sign-in

Until it is set up, anyone can register any number of players. To allow one
player per GitHub account:

1. On GitHub: Settings → Developer settings → OAuth Apps → New OAuth App.
   - Homepage URL: `https://fieldhand.example.com`
   - Authorization callback URL: `https://fieldhand.example.com/auth/github`
2. Generate a client secret and write both values in `/etc/fieldhand.env`
   (readable by root only):

   ```
   FIELDHAND_GITHUB_CLIENT_ID=...
   FIELDHAND_GITHUB_CLIENT_SECRET=...
   ```

3. `sudo systemctl restart fieldhand`

The app asks GitHub for no permissions: it only reads the public profile.

## Backups

Every day at 04:00 UTC `deploy/backup.sh` saves a compressed copy of the
database in `/var/lib/fieldhand/backups` and keeps the last 14. Run one now
with `sudo systemctl start fieldhand-backup`.

To keep copies off the machine as well, for free with Oracle Object Storage:

1. Storage → Buckets → Create bucket `fieldhand-backups` (private).
2. In the bucket, create a pre-authenticated request for the whole bucket that
   **only permits object writes**, with a far expiration date.
3. Put its URL in `/etc/fieldhand.env` as `FIELDHAND_BACKUP_URL=...` (it ends
   in `/o/`). The URL lets anyone write to the bucket, so keep it secret, but
   it cannot read, list or delete anything.

To restore a backup:

```bash
sudo systemctl stop fieldhand-house fieldhand
gunzip -c fieldhand-YYYYMMDD-HHMMSS.db.gz | sudo -u fieldhand tee /var/lib/fieldhand/fieldhand.db >/dev/null
sudo rm -f /var/lib/fieldhand/fieldhand.db-wal /var/lib/fieldhand/fieldhand.db-shm
sudo systemctl start fieldhand fieldhand-house
```

The world pauses while the server is stopped, so nobody starves meanwhile.

## House bots

A new village is empty. House bots (`examples/house_bots.py`) keep it alive
with trade, prices and work until real players arrive. They play by the same
rules and through the same API as everybody else; their names start with
`house-`. Create them on the server, without GitHub:

```bash
cd /opt/fieldhand
for name in ada bert cleo dov ema finn gus hana ivo juno kai lena; do
  echo "\"house-$name\": \"$(sudo -u fieldhand FIELDHAND_DB=/var/lib/fieldhand/fieldhand.db \
    .venv/bin/fieldhand --add-player house-$name)\","
done
```

Put the lines in `/var/lib/fieldhand/house.json` as one JSON object (owned by
`fieldhand`, mode 600), then:

```bash
sudo install -m 644 deploy/fieldhand-house.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now fieldhand-house
```

- Data: `/var/lib/fieldhand/fieldhand.db`. It is backed up every day (see below).
- Logs: `journalctl -u fieldhand -f`.
- Restarts and crashes pause the world: nobody dies while the server is down.
