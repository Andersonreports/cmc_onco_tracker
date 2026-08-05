# CMC-ONCO Tracker — Server Edition

Server-hosted version of the Anderson Lab Wetlab/Report Tracker, now served
by a small FastAPI backend instead of GitHub Pages. No login — open access.

## Architecture

- **`frontend/`** — the tracker UI (`index.html`). All tracker data
  reads/writes, file storage, and email sending happen client-side against
  the Google Apps Script Web App defined in `apps_script/Code.gs` (deployed
  separately, inside the Google Sheet — see `apps_script/DEPLOY.md`). That
  Apps Script deployment is the application's data backend; nothing here
  duplicates it.
- **`backend/`** — a FastAPI app (`backend.py`) that handles login/roles and
  serves the tracker pages plus their static assets from `frontend/`.

## Run locally

### Windows — one-click start

Double-click `start.bat` in the repo root. It creates a virtual environment
on first run, installs dependencies, starts the server, and opens the
tracker in your default browser automatically. Close the "CMC-ONCO Tracker
Server" window to stop it.

### macOS/Linux — one-click start

Double-click `start.command` in the repo root (macOS may require
right-click → Open the first time, since it's from an unidentified
developer). It creates a virtual environment on first run, installs
dependencies, starts the server, and opens the tracker in your default
browser automatically. Press Ctrl+C in the terminal window to stop it.

### Manual (any OS)

```bash
cd backend
pip install -r requirements.txt
uvicorn backend:app --reload
```

Visit `http://localhost:8000/`.

## Deploy on a server

### Option A — Docker

```bash
docker build -t cmc-onco-tracker .
docker run -d --name tracker -p 8000:8000 cmc-onco-tracker
```

Put a TLS-terminating reverse proxy (nginx, Caddy, or your cloud load
balancer) in front of port 8000 — the app itself doesn't handle TLS.

### Option B — systemd + nginx on a VPS

1. Clone the repo on the server, `pip install -r backend/requirements.txt`.
2. Create `/etc/systemd/system/cmc-onco-tracker.service`:

   ```ini
   [Unit]
   Description=CMC-ONCO Tracker
   After=network.target

   [Service]
   User=www-data
   WorkingDirectory=/opt/cmc_onco_tracker/backend
   ExecStart=/opt/cmc_onco_tracker/.venv/bin/gunicorn backend:app \
     -k uvicorn.workers.UvicornWorker -w 2 -b 127.0.0.1:8000
   Restart=always

   [Install]
   WantedBy=multi-user.target
   ```

3. `systemctl enable --now cmc-onco-tracker`
4. Reverse-proxy `https://your-domain/` → `http://127.0.0.1:8000/` with
   nginx or Caddy, and obtain a TLS cert (e.g. via `certbot`).

## Migrating off GitHub Pages

This tracker was previously hosted via GitHub Pages. That hosting has been
disabled in favor of the server deployment above (see "Deploy on a server").
Both still run against the same Google Sheet / Apps Script backend, so no
data migration is needed — only where the page is served from changed. When
you update the tracker UI or `apps_script/Code.gs`, redeploy the Apps Script
Web App (see `apps_script/DEPLOY.md`).
