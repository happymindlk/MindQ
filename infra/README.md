# Host configuration templates

Sanitized reference copies of the configs on the Lightsail API nodes, kept in
version control so proxy timeouts, body limits, restart policy and log rotation
can be reviewed (audit item P2-12). They hold no hostnames, IPs, or secrets;
fill the `<...>` placeholders per host.

| File | Installs to |
|------|-------------|
| `nginx-mindq.conf` | `/etc/nginx/sites-available/mindq` (symlink into `sites-enabled`) |
| `mindq.service` | `/etc/systemd/system/mindq.service` |
| `mindq-worker.service` | `/etc/systemd/system/mindq-worker.service` |
| `logrotate-mindq` | `/etc/logrotate.d/mindq` |

Assumed layout: code in `/opt/mindq/backend` with a venv at `.venv`, a `mindq`
system user, secrets in `/etc/mindq/mindq.env` (root-owned, `0600`), logs in
`/var/log/mindq/` (owned by `mindq`).

Key values (keep in sync with `DEPLOYMENT.md`):

- `proxy_read_timeout 90s`: above asyncpg `command_timeout` (60s) and PDF rendering.
- `client_max_body_size 15m`: above the 10 MiB JD PDF upload cap.
- `TimeoutStopSec=40`: above Uvicorn `--timeout-graceful-shutdown 30`.
- `Restart=always`, `KillSignal=SIGTERM` on both units.

After changing a template, apply it on **both** nodes, then run
`nginx -t && systemctl reload nginx` or `systemctl daemon-reload && systemctl restart <unit>`.
