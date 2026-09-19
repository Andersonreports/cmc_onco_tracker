import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from auth import COOKIE_NAME, read_session
import access
import cmc_sample_tracking as tracking

TRACKER_KEY = "cmc-sample-tracking"


def require_tracker_access(request: Request) -> dict:
    sess = read_session(request.cookies.get(COOKIE_NAME))
    if not sess:
        raise HTTPException(status_code=401, detail="Please sign in.")
    if not access.can_open_tracker(sess.get("acc"), TRACKER_KEY):
        raise HTTPException(status_code=403, detail="This tracker is not available for your role.")
    return sess


router = APIRouter(prefix="/cmc-sample-tracking/api", dependencies=[Depends(require_tracker_access)])


# Mirrors the standalone backend's GET /api/exec?action=getAllData|getRegistrations
@router.get("/exec")
def exec_get(action: str = ""):
    try:
        if action == "getAllData":
            return tracking.get_all_data()
        if action == "getRegistrations":
            return {"registrations": tracking.get_registration_rows()}
        return JSONResponse({"error": "Invalid action"}, status_code=400)
    except tracking.SampleTrackingError as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    except Exception as exc:  # noqa: BLE001 - surfaced to the frontend as an error toast
        print(f"[cmc-sample-tracking] GET /exec error: {exc}")
        return JSONResponse({"error": str(exc)}, status_code=500)


# Mirrors the standalone backend's POST /api/exec { action: 'sendEmail', ... }
# The frontend posts as text/plain to dodge a CORS preflight, so the body is
# read raw and parsed as JSON regardless of the declared content type.
@router.post("/exec")
async def exec_post(request: Request):
    try:
        raw = await request.body()
        body = json.loads(raw or b"{}")
        action = body.get("action")

        if action == "sendEmail":
            return tracking.send_email_action(body)
        if action == "updateReportReleasedDateBulk":
            return tracking.update_report_released_date_bulk(
                body.get("items") or [], body.get("value") or "")
        return JSONResponse({"error": "Invalid action"}, status_code=400)
    except Exception as exc:  # noqa: BLE001 - surfaced to the frontend as an error toast
        print(f"[cmc-sample-tracking] POST /exec error: {exc}")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)
