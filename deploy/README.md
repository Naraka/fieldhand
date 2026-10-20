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

- Data: `/var/lib/fieldhand/fieldhand.db`. Back it up with `sqlite3 fieldhand.db ".backup copy.db"`.
- Logs: `journalctl -u fieldhand -f`.
- Restarts and crashes pause the world: nobody dies while the server is down.
