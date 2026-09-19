# Anderson Trackings

Server-hosted hub of Anderson Diagnostics' internal trackers — one FastAPI
app (`backend/backend.py`) that handles mobile+OTP login, per-user roles,
and serves every tracker's frontend from `frontend/`. Historically this repo
was just the CMC-ONCO Tracker (hence the repo name); it has since grown into
the whole "Anderson Trackings" app.

Read this file before re-exploring the codebase — it's kept up to date with
the current tracker roster and the pattern used to add a new one.

## Sections and trackers

The app is organized as **sections** (top-level areas, e.g. "Bioinfo
Trackers") containing **trackers** (an individual tool). Both are declared
in `backend/access.py`:

- `SECTIONS` — `cmc`, `anderson` (top-level), `bioinfo` (nested under
  `anderson`). Each has a landing page (e.g. `frontend/bioinfo.html`).
- `TRACKERS` — one entry per tracker: its URL path, the frontend page it
  serves, and which section it belongs to.
- `ROLES` — what an admin actually assigns to a user. A role reaches one or
  more sections (which expands to every tracker under them) or, for
  single-tracker access, names trackers directly (see
  `clinical-history-only`). Access checks (`can_open_tracker`,
  `can_open_section`) and the admin UI's grant list (`GRANTABLE`, `LABELS`)
  are derived from `TRACKERS` automatically — add a tracker there and it
  shows up everywhere else on its own.

Current trackers (all under **Bioinfo Trackers**, `/bioinfo/`, unless noted):

| Tracker | Path | Backend | Frontend |
|---|---|---|---|
| CMC ONCO Tracker (section: `cmc`) | `/cmc-onco/` | gated static page; all data/mail lives client-side in `apps_script/Code.gs` (a separate Google Apps Script Web App) | `frontend/cmc-onco.html` |
| Germline Exome Sample Tracker | `/exome-tracker/` | own FastAPI router + MySQL, `backend/exome_api.py` / `backend/exome_roles.py` | `frontend/exome-tracker/index.html` |
| Clinical History Tracker | `/clinical-history/` | gated static page, no server API of its own | `frontend/clinical-history.html` |
| CMC Sample Tracking | `/cmc-sample-tracking/` | own FastAPI router, `backend/cmc_sample_tracking_api.py` / `backend/cmc_sample_tracking.py` (Google Sheets read, SMTP mail, daily TAT-alert cron) | `frontend/cmc-sample-tracking.html` |
| Coverage Checker (section: `anderson`) | `/anderson-coverage/` | separate Flask/WSGI app in `anderson-coverage/`, mounted in-process behind the session gate | (its own app) |

### How a tracker is wired into `backend.py`

Every gated page follows the same shape:

```python
@app.get("/<tracker>", include_in_schema=False)
def x_slash():
    return RedirectResponse("/<tracker>/")

@app.get("/<tracker>/", response_class=HTMLResponse)
def x_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if not access.can_open_tracker(sess["acc"], "<tracker-key>"):
        return _home_for(sess)
    return _serve("<page>.html")  # or read+return HTMLResponse directly
                                  # if the page needs a server-injected
                                  # <script> (see exome-tracker, cmc-sample-tracking)
```

A tracker with its own API (exome, cmc-sample-tracking) adds a
`fastapi.APIRouter(prefix="/<tracker>/api", dependencies=[Depends(require_tracker_access)])`
in its own module and `app.include_router(...)`s it in `backend.py`. A
tracker with no server-side state of its own (clinical-history) is just the
gated static page — its "backend" is either nothing or an external service
called client-side.

### Adding a new tracker — checklist

1. `backend/access.py`: add an entry to `TRACKERS` (label, path, page,
   section).
2. `backend/backend.py`: add the `/<tracker>` + `/<tracker>/` routes; if it
   has its own API, add a `<tracker>_api.py` router and `include_router` it.
3. Drop the frontend page under `frontend/` (flat `.html` for a simple gated
   page, or a subfolder if it needs its own bundled assets, like
   `exome-tracker/`).
4. Add a card to `frontend/bioinfo.html` (or the relevant section page) —
   `<a class="card active" href="/<tracker>/" data-tracker="<tracker-key>">`.
   The `data-tracker` attribute is what `access-gate.js` uses to hide the
   card from users who can't open it — no other frontend change needed.
5. If the tracker needs secrets/config, prefix its env vars distinctly
   (e.g. `CMC_ST_*` for CMC Sample Tracking) in `backend/.env.example`, and
   load them via `env_loader.load_backend_env()` like every other module.

No changes to `ROLES` are needed for a tracker under an existing section —
every role that already reaches that section picks up the new tracker
automatically.

## Run locally

```bash
cd backend
pip install -r requirements.txt
uvicorn backend:app --reload --port 8010
```

Visit `http://localhost:8010/`.

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

## Login and roles

Login is mobile number + OTP against an external genetics-auth service
(`backend/genetics_auth_client.py`), not a local password (except the
separate admin password reset flow in `backend/admin_api.py`). A signed
session cookie (`backend/auth.py`) then carries either a role name or a
raw list of tracker keys (`backend/access.py`'s `normalize()` handles both,
so old pre-role stored values keep working). Admins manage per-user roles at
`/admin/`.

## Notes on individual trackers

- **CMC ONCO Tracker**: all tracker data reads/writes, file storage, and
  email sending happen client-side against the Google Apps Script Web App
  defined in `apps_script/Code.gs` (deployed separately, inside the Google
  Sheet — see `apps_script/DEPLOY.md`). That Apps Script deployment is this
  tracker's data backend; nothing in `backend/` duplicates it. It was
  previously hosted via GitHub Pages; that hosting has been disabled in
  favor of this server deployment, against the same Google Sheet/Apps
  Script backend, so no data migration was needed.
- **CMC Sample Tracking**: ported from the standalone
  `cmc_sampletracker_database` repo (Node/Express + Google Sheets API +
  SMTP + a daily TAT-alert cron job) into `backend/cmc_sample_tracking.py`
  / `backend/cmc_sample_tracking_api.py`, action-for-action the same
  behavior, running in-process instead of as a second server. That repo's
  own README explains the port and keeps its Node backend as a reference
  implementation / fallback standalone deployment.
