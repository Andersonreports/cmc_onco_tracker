"""
backend.py
───────────────────────────────────────────────────────────────
Anderson Trackings server.

Serves the frontend with role-based access control:

  Public
    GET /login          → sign-in page (id + password + OTP)
    /auth/*             → auth API (see auth.py)
    non-HTML assets     → images / js / css served statically

  Authenticated (role-gated)
    GET /               → admin only  → suite-picker landing.
                          cmc  → redirected to /cmc/
                          anderson → redirected to /anderson/
    GET /cmc/           → admin + cmc        → CMC trackers page
    GET /cmc-onco/      → admin + cmc        → CMC ONCO tracker app
    GET /anderson/      → admin + anderson   → Anderson trackers page

Anyone not signed in is redirected to /login. A signed-in user who requests a
page outside their role is sent back to their own home page.
"""

from pathlib import Path

from fastapi import FastAPI, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from auth import router as auth_router, read_session, ROLE_HOME

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Anderson Trackings")
app.include_router(auth_router)


@app.get("/health")
def health():
    return {"status": "Anderson Trackings running"}


# ── Helpers ───────────────────────────────────────────────────

def _serve(rel_path: str) -> HTMLResponse:
    # no-store: these pages are auth-gated and must never be cached by the
    # browser (prevents stale pages and back/forward showing gated content).
    return HTMLResponse(
        (FRONTEND_DIR / rel_path).read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


def _to_login() -> RedirectResponse:
    return RedirectResponse("/login")


def _home_for(role: str) -> RedirectResponse:
    return RedirectResponse(ROLE_HOME.get(role, "/login"))


# ── Login page (public) ───────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if sess:  # already signed in → go to your home
        return _home_for(sess["role"])
    return _serve("login.html")


# ── Landing (admin only) ──────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def landing(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] == "admin":
        return _serve("index.html")
    return _home_for(sess["role"])  # cmc/anderson → their own suite


# ── CMC suite (admin + cmc) ───────────────────────────────────

@app.get("/cmc", include_in_schema=False)
def cmc_slash():
    return RedirectResponse("/cmc/")


@app.get("/cmc/", response_class=HTMLResponse)
def cmc_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] in ("admin", "cmc"):
        return _serve("cmc/index.html")
    return _home_for(sess["role"])


@app.get("/cmc-onco", include_in_schema=False)
def cmc_onco_slash():
    return RedirectResponse("/cmc-onco/")


@app.get("/cmc-onco/", response_class=HTMLResponse)
def cmc_onco_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] in ("admin", "cmc"):
        return _serve("cmc-onco/index.html")
    return _home_for(sess["role"])


# ── Anderson suite (admin + anderson) ─────────────────────────

@app.get("/anderson", include_in_schema=False)
def anderson_slash():
    return RedirectResponse("/anderson/")


@app.get("/anderson/", response_class=HTMLResponse)
def anderson_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] in ("admin", "anderson"):
        return _serve("anderson/index.html")
    return _home_for(sess["role"])


# ── Static assets — non-HTML only ─────────────────────────────
# HTML is served exclusively through the role-gated routes above; this mount
# (registered last, so it's a fallback) blocks .html so pages can't be fetched
# directly to bypass auth, while images / js / css load normally.
class AssetFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.lower().endswith((".html", ".htm")) or path in ("", "."):
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Not found", status_code=404)
        return await super().get_response(path, scope)


app.mount("/", AssetFiles(directory=FRONTEND_DIR, html=False), name="assets")
