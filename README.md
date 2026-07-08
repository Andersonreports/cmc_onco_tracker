# CMC-ONCO Tracker — Server Edition

Login-gated, server-hosted version of the Anderson Lab Wetlab/Report Tracker.
This repo replicates [Wetlab_tracker](https://github.com/Andersonreports/Wetlab_tracker)
(which stays published on GitHub Pages) but adds a FastAPI backend in front of
the tracker page so it can run on your own server with authentication.

## Architecture

- **`frontend/`** — the tracker UI (`report_tracker.html`) and login page
  (`tracker_login.html`). All tracker data reads/writes, file storage, and
  email sending happen client-side against the Google Apps Script Web App
  defined in `apps_script/Code.gs` (deployed separately, inside the Google
  Sheet — see `apps_script/DEPLOY.md`). That Apps Script deployment is the
  application's data backend; nothing here duplicates it.
- **`backend/`** — a small FastAPI app (`backend.py` + `tracker_auth.py`)
  that serves the frontend under `/tracker` behind a username/password +
  JWT session cookie, so the tracker isn't publicly reachable the way the
  GitHub Pages copy is.

## One-time setup

```bash
cd backend
pip install -r requirements.txt
python create_credentials.py     # writes TRACKER_USER / TRACKER_PASS_HASH into backend/.env
```

Then add a session-signing secret to `backend/.env` (see `.env.example`):

```bash
python -c "import secrets; print(secrets.token_hex(32))"
# paste the output as TRACKER_SECRET=... in backend/.env
```

## Run locally

```bash
cd backend
uvicorn backend:app --reload
```

Visit `http://localhost:8000/tracker/login`.

> Local HTTP note: the session cookie is `Secure` by default, which browsers
> only send back over HTTPS. For local `http://` testing, set
> `TRACKER_COOKIE_SECURE=false` in `backend/.env`. Leave it unset (or `true`)
> on any real deployment.

## Deploy on a server

### Option A — Docker

```bash
docker build -t cmc-onco-tracker .
docker run -d --name tracker \
  --env-file backend/.env \
  -p 8000:8000 \
  cmc-onco-tracker
```

Put a TLS-terminating reverse proxy (nginx, Caddy, or your cloud load
balancer) in front of port 8000 — the app itself doesn't handle TLS.

### Option B — systemd + nginx on a VPS

1. Clone the repo on the server, run the one-time setup above.
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
   EnvironmentFile=/opt/cmc_onco_tracker/backend/.env

   [Install]
   WantedBy=multi-user.target
   ```

3. `systemctl enable --now cmc-onco-tracker`
4. Reverse-proxy `https://your-domain/` → `http://127.0.0.1:8000/` with
   nginx or Caddy, and obtain a TLS cert (e.g. via `certbot`).

Either way, once TLS is in front of the app, `TRACKER_COOKIE_SECURE` should
stay at its default (`true`).

## Relationship to the GitHub Pages copy

`Wetlab_tracker` (the original repo) continues to publish the same tracker
page publicly via GitHub Pages, with no login. This repo is a separate,
authenticated deployment of the same frontend for server hosting — both can
run at the same time against the same Google Sheet / Apps Script backend.
When you update the tracker UI or `apps_script/Code.gs`, apply the change in
both repos and redeploy the Apps Script Web App (see `apps_script/DEPLOY.md`).
