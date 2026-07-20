
from pathlib import Path

from fastapi import FastAPI, Cookie
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from auth import router as auth_router, read_session, ROLE_HOME
from admin_api import router as admin_router

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Anderson Trackings")
app.include_router(auth_router)
app.include_router(admin_router)


@app.get("/health")
def health():
    return {"status": "Anderson Trackings running"}


# ── Helpers ───────────────────────────────────────────────────

def _serve(rel_path: str) -> HTMLResponse:

    return HTMLResponse(
        (FRONTEND_DIR / rel_path).read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


def _to_login() -> RedirectResponse:
    return RedirectResponse("/login")


def _home_for(role: str) -> RedirectResponse:
    return RedirectResponse(ROLE_HOME.get(role, "/login"))


# ── Login page (public) ───────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
def login_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if sess:
        return _home_for(sess["role"])
    return _serve("login.html")


# ── Landing (admin only) ──────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def landing(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] == "admin":
        return _serve("landing.html")
    return _home_for(sess["role"])


# ── Admin: user management dashboard (admin only) ─────────────

@app.get("/admin", include_in_schema=False)
def admin_slash():
    return RedirectResponse("/admin/")


@app.get("/admin/", response_class=HTMLResponse)
def admin_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if sess["role"] == "admin":
        return _serve("admin.html")
    return _home_for(sess["role"])


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
        return _serve("cmc.html")
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
        return _serve("cmc-onco.html")
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
        return _serve("anderson.html")
    return _home_for(sess["role"])


class AssetFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.lower().endswith((".html", ".htm")) or path in ("", "."):
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Not found", status_code=404)
        return await super().get_response(path, scope)


app.mount("/", AssetFiles(directory=FRONTEND_DIR, html=False), name="assets")
