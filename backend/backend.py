from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

app = FastAPI(title="Anderson Lab Report Tracker")


@app.get("/health")
def health():
    return {"status": "Anderson Report Tracker running"}


# Serves frontend/index.html at "/" and the rest of frontend/ (xlsx.full.min.js,
# header_logo.png, etc.) as static files. No auth — same as the GitHub Pages copy.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
