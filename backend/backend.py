
import json
from pathlib import Path

from fastapi import FastAPI, Cookie, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from auth import router as auth_router, read_session, renew_session_cookie, COOKIE_NAME
from admin_api import router as admin_router
from exome_api import router as exome_tracker_router
import access
import exome_roles
import reports_client
import role_store

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Anderson Trackings")
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(exome_tracker_router)


@app.exception_handler(reports_client.ReportsAPIError)
async def reports_api_unavailable(request: Request, exc: reports_client.ReportsAPIError):
    return JSONResponse(
        {"error": "The Exome Tracker reports service is unreachable. It is hosted by IT — "
                  "check that it is running and connected, then retry."},
        status_code=503,
    )


@app.middleware("http")
async def renew_idle_session(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/auth/logout"):
        return response
    sess = read_session(request.cookies.get(COOKIE_NAME))
    if sess:
        renew_session_cookie(response, sess)
    return response


@app.get("/health")
def health(check: str | None = None):
    info = {
        "status": "Anderson Trackings running",
        "role_backend": role_store.backend_name(),
        "role_count": len(role_store.all()),
        "reports_api": reports_client.status(),
    }
    if check:
        mobile = role_store.normalize_mobile(check)
        mapping = role_store.get(mobile)
        info["check_mobile"] = mobile
        info["check_role"] = mapping["role"] if mapping else None
    return info


def _serve(rel_path: str) -> HTMLResponse:
    return HTMLResponse(
        (FRONTEND_DIR / rel_path).read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


def _to_login() -> RedirectResponse:
    return RedirectResponse("/login")


def _home_for(sess: dict) -> RedirectResponse:
    return RedirectResponse(access.home_for(sess.get("acc")))


def _gate(sess, allowed: bool, page: str):
    if not allowed:
        return _home_for(sess)
    return _serve(page)


@app.get("/login", response_class=HTMLResponse)
def login_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if sess:
        return _home_for(sess)
    return _serve("login.html")


@app.get("/", response_class=HTMLResponse)
def landing(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if not sess["acc"]:
        return _to_login()
    return _serve("landing.html")


@app.get("/admin", include_in_schema=False)
def admin_slash():
    return RedirectResponse("/admin/")


@app.get("/admin/", response_class=HTMLResponse)
def admin_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    return _gate(sess, access.is_admin(sess["acc"]), "admin.html")


@app.get("/cmc", include_in_schema=False)
def cmc_slash():
    return RedirectResponse("/cmc/")


@app.get("/cmc/", response_class=HTMLResponse)
def cmc_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    return _gate(sess, access.can_open_section(sess["acc"], "cmc"), "cmc.html")


@app.get("/cmc-onco", include_in_schema=False)
def cmc_onco_slash():
    return RedirectResponse("/cmc-onco/")


@app.get("/cmc-onco/", response_class=HTMLResponse)
def cmc_onco_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    return _gate(sess, access.can_open_tracker(sess["acc"], "cmc-onco"), "cmc-onco.html")


@app.get("/anderson", include_in_schema=False)
def anderson_slash():
    return RedirectResponse("/anderson/")


@app.get("/anderson/", response_class=HTMLResponse)
def anderson_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    return _gate(sess, access.can_open_section(sess["acc"], "anderson"), "anderson.html")


@app.get("/bioinfo", include_in_schema=False)
def bioinfo_slash():
    return RedirectResponse("/bioinfo/")


@app.get("/bioinfo/", response_class=HTMLResponse)
def bioinfo_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    return _gate(sess, access.can_open_section(sess["acc"], "bioinfo"), "bioinfo.html")


@app.get("/exome-tracker", include_in_schema=False)
def exome_tracker_slash():
    return RedirectResponse("/exome-tracker/")


@app.get("/exome-tracker/", response_class=HTMLResponse)
def exome_tracker_page(anderson_session: str | None = Cookie(default=None)):
    sess = read_session(anderson_session)
    if not sess:
        return _to_login()
    if not access.can_open_tracker(sess["acc"], "exome"):
        return _home_for(sess)

    mobile = sess.get("sub", "")
    mapping = role_store.get(mobile) or {}
    user = {
        "username": (mapping.get("name") or "").strip() or mobile,
        "role": exome_roles.role_for_accesses(sess["acc"]),
    }
    payload = json.dumps(user).replace("</", "<\\/")

    html = (FRONTEND_DIR / "exome-tracker" / "index.html").read_text(encoding="utf-8")
    html = html.replace(
        "</head>", f"<script>window.TRACKER_USER = {payload};</script>\n</head>", 1)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate",
                 "Pragma": "no-cache"},
    )


class AssetFiles(StaticFiles):
    async def get_response(self, path, scope):
        if path.lower().endswith((".html", ".htm")) or path in ("", "."):
            from starlette.responses import PlainTextResponse
            return PlainTextResponse("Not found", status_code=404)
        return await super().get_response(path, scope)


app.mount("/", AssetFiles(directory=FRONTEND_DIR, html=False), name="assets")
