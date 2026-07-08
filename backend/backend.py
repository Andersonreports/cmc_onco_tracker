from fastapi import FastAPI
from fastapi.responses import RedirectResponse

from tracker_auth import router as tracker_router

# No CORS middleware: the frontend is served same-origin by this app (under
# /tracker), and it talks to the Google Apps Script backend directly from the
# browser — that's a separate origin governed by Google's own CORS, not ours.
# A wildcard allow_origins combined with allow_credentials would be an open
# security hole for no functional benefit.
app = FastAPI(title="Anderson Lab Report Tracker")

app.include_router(tracker_router)


@app.get("/health")
def health():
    return {"status": "Anderson Report Tracker running"}


@app.get("/")
def root():
    return RedirectResponse("/tracker/login")
