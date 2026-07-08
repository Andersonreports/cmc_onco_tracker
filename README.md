# CMC-ONCO Tracker — Server Edition

Server-hosted version of the Anderson Lab Wetlab/Report Tracker. This repo
replicates [Wetlab_tracker](https://github.com/Andersonreports/Wetlab_tracker)
(which stays published on GitHub Pages) with a small FastAPI backend added so
it can also run on your own server. No login — open access, same as the
GitHub Pages copy.

## Architecture

- **`frontend/`** — the tracker UI (`index.html`). All tracker data
  reads/writes, file storage, and email sending happen client-side against
  the Google Apps Script Web App defined in `apps_script/Code.gs` (deployed
  separately, inside the Google Sheet — see `apps_script/DEPLOY.md`). That
  Apps Script deployment is the application's data backend; nothing here
  duplicates it.
- **`backend/`** — a minimal FastAPI app (`backend.py`) that serves
  `frontend/` as a static site (`index.html` at `/`, plus `xlsx.full.min.js`
  and `header_logo.png`).
- **`index.html`** at the repo root — a copy of `frontend/index.html`, kept
  in sync for quick viewing/reference or an alternate static host.

## Run locally

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

## Relationship to the GitHub Pages copy

`Wetlab_tracker` (the original repo) continues to publish the same tracker
page publicly via GitHub Pages. This repo is the same frontend served from a
real backend process instead, for hosting on your own server. Both run
against the same Google Sheet / Apps Script backend. When you update the
tracker UI or `apps_script/Code.gs`, apply the change in both repos and
redeploy the Apps Script Web App (see `apps_script/DEPLOY.md`).
